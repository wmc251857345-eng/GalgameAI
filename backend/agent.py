"""AI 管家：工具调用式对话代理，管理本地 Galgame 库。

架构：LLM 只能通过受控工具动作（搜索/查看/修正/换封面/重分析），
所有写操作复用 JsApi 的校验逻辑（白名单字段 + source='manual' 留痕）。
"""

import json

from . import paths  # noqa: F401  (keep for future use)
from .utils import now_iso

SYSTEM_PROMPT = """你是 GALA（Galgame AI Library Agent）的 AI 管家，负责管理用户的本地 Galgame 游戏库。
你的能力全部通过调用工具实现，规则：
1. 始终用简体中文回答，简洁、友好，像懂行的朋友，别用"作为AI"这类话。
2. 用户说"搞错了/不是XX是XX/改一下"时：如果用户直接给出了正确信息（名称/厂商等），调用 correct_game 按用户给的原样填入，然后告知结果；用户没给全时，再 get_game + search_providers 补齐资料后调用 correct_game。
3. 推荐游戏（如"哪个是纯爱"）：用 search_games 按标签/时长/评分筛选，结合简介给理由，最多 5 个。
4. 用户要求修正/更改资料时，必须调用 update_game_info 或 set_game_cover 工具真正修改，然后告知结果。严禁在未调用工具的情况下声称已修改。
5. 库的统计数字用工具查，不猜测。
6. 用户没指定游戏时，可以问一句是哪个游戏，或先用 search_games 缩小范围。
7. 回答里的所有数字（数量/时长/年份/评分）必须严格与工具返回一致，禁止编造或脑补。
8. 工具信息足够后就立刻回答，不要重复调用同一个工具；每轮最多连续调用 2~3 个工具。
"""

TOOLS = [
    {"type": "function", "function": {
        "name": "search_games",
        "description": "在本地游戏库中搜索游戏，可按关键词/标签/厂商/年份/状态过滤",
        "parameters": {"type": "object", "properties": {
            "q": {"type": "string", "description": "标题关键词（可空）"},
            "tag": {"type": "string", "description": "标签，如 纯爱/废萌/悬疑（可空）"},
            "maker": {"type": "string", "description": "厂商名（可空）"},
            "year": {"type": "string", "description": "发售年份，如 2020（可空）"},
            "status": {"type": "integer", "description": "2=已入库 1=待确认 3=已跳过（可空）"},
        }, "required": []}}},
    {"type": "function", "function": {
        "name": "get_game",
        "description": "获取单个游戏的完整信息（简介/标签/时长/路径等）",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "integer"},
        }, "required": ["id"]}}},
    {"type": "function", "function": {
        "name": "get_library_stats",
        "description": "获取游戏库统计（总数/已入库/待确认/总时长/厂商数）",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "list_facets",
        "description": "列出库里的标签/厂商/年份维度及数量",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "search_providers",
        "description": "在 VNDB / Bangumi 搜索游戏的外部资料（标题/厂商/发售日/简介/封面）",
        "parameters": {"type": "object", "properties": {
            "keyword": {"type": "string"},
        }, "required": ["keyword"]}}},
    {"type": "function", "function": {
        "name": "correct_game",
        "description": "按用户提供的正确信息修正游戏资料：id 必填，其余字段用户给什么就填什么（title/title_jp/title_zh/title_en/maker/brand/released/description/vndb_id）。这是修正动作的首选工具，改完要告知用户。",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "integer"},
            "title": {"type": "string", "description": "正确标题"},
            "title_jp": {"type": "string", "description": "正确日文名"},
            "title_zh": {"type": "string", "description": "正确中文名"},
            "title_en": {"type": "string", "description": "正确英文/罗马音名"},
            "maker": {"type": "string", "description": "正确厂商"},
            "brand": {"type": "string", "description": "正确品牌"},
            "released": {"type": "string", "description": "正确发售日 YYYY-MM-DD"},
            "description": {"type": "string", "description": "正确简介"},
            "vndb_id": {"type": "string", "description": "VNDB 条目 ID（形如 v12345）"},
        }, "required": ["id"]}}},
    {"type": "function", "function": {
        "name": "update_game_info",
        "description": "修正一个游戏的资料（仅限白名单字段：title/title_zh/title_jp/title_en/maker/brand/released/rating/length_minutes/description/hanhua/vndb_id）",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "integer"},
            "title": {"type": "string"},
            "title_zh": {"type": "string"},
            "title_jp": {"type": "string"},
            "title_en": {"type": "string"},
            "maker": {"type": "string"},
            "brand": {"type": "string"},
            "released": {"type": "string"},
            "rating": {"type": "number"},
            "length_minutes": {"type": "integer"},
            "description": {"type": "string"},
            "hanhua": {"type": "boolean"},
            "vndb_id": {"type": "string"},
        }, "required": ["id"]}}},
    {"type": "function", "function": {
        "name": "set_game_cover",
        "description": "从 URL 下载并设置为某游戏的封面",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "integer"},
            "url": {"type": "string"},
        }, "required": ["id", "url"]}}},
    {"type": "function", "function": {
        "name": "reanalyze_game",
        "description": "触发某游戏的后台重新分析（重新匹配 VNDB/BGM + AI 润色），异步执行",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "integer"},
        }, "required": ["id"]}}},
]


class AgentService:
    """管家服务：持 DB/配置引用，执行工具调用循环。无状态（历史在库中）。"""

    def __init__(self, db, cfg):
        self._db = db
        self._cfg = cfg
        self._js = None
        self._prov_cache = {}  # keyword -> (ts, results)，TTL 5 分钟，省请求+防限速

    @property
    def _api(self):
        """懒加载 JsApi，复用其校验过的写操作。"""
        if self._js is None:
            from .api import JsApi
            self._js = JsApi(self._db, self._cfg)
        return self._js

    # ---------- 工具实现 ----------
    def _tool_search_games(self, args):
        sql = "SELECT * FROM games WHERE 1=1"
        params = []
        q = (args.get("q") or "").strip()
        tag = (args.get("tag") or "").strip()
        maker = (args.get("maker") or "").strip()
        year = (args.get("year") or "").strip()
        status = args.get("status")
        if q:
            sql += " AND (title LIKE ? OR title_jp LIKE ? OR title_en LIKE ? OR title_zh LIKE ?)"
            params += [f"%{q}%"] * 4
        if maker:
            sql += " AND maker LIKE ?"
            params.append(f"%{maker}%")
        if year:
            sql += " AND substr(released,1,4)=?"
            params.append(year)
        if status is not None:
            sql += " AND status=?"
            params.append(int(status))
        sql += " ORDER BY id LIMIT 20"
        rows = self._db.query(sql, params)
        tag_map = self._tag_map()
        out = []
        for g in rows:
            out.append({
                "id": g["id"], "title": g["title"], "title_jp": g["title_jp"],
                "maker": g["maker"], "released": g["released"],
                "rating": round(g["rating"] / 10, 1) if g["rating"] and g["rating"] > 20 else g["rating"],
                "length_minutes": g["length_minutes"], "status": g["status"],
                "favorite": g["favorite"], "hanhua": g["hanhua"],
                "playtime_hours": round((g["playtime_seconds"] or 0) / 3600, 1),
                "tags": tag_map.get(g["id"], []),
            })
        # 按标签过滤（内存过滤，因为标签在关联表）
        if tag:
            out = [g for g in out if tag in g["tags"]]
        return {"count": len(out), "games": out}

    def _tag_map(self):
        m = {}
        for t in self._db.query(
                "SELECT gt.game_id, t.name FROM game_tags gt JOIN tags t ON t.id=gt.tag_id"):
            m.setdefault(t["game_id"], []).append(t["name"])
        return m

    def _tool_get_game(self, args):
        g = self._db.query_one("SELECT * FROM games WHERE id=?", (int(args.get("id")),))
        if not g:
            return {"error": "游戏不存在"}
        tags = [t["name"] for t in self._db.query(
            "SELECT t.name FROM tags t JOIN game_tags gt ON t.id=gt.tag_id"
            " WHERE gt.game_id=? ORDER BY gt.rowid", (g["id"],))]
        return {
            "id": g["id"], "title": g["title"], "title_jp": g["title_jp"],
            "title_zh": g["title_zh"], "title_en": g["title_en"],
            "maker": g["maker"], "brand": g["brand"], "released": g["released"],
            "rating": round(g["rating"] / 10, 1) if g["rating"] and g["rating"] > 20 else g["rating"],
            "length_minutes": g["length_minutes"], "status": g["status"],
            "source": g["source"], "vndb_id": g["vndb_id"],
            "favorite": g["favorite"], "hanhua": g["hanhua"],
            "playtime_hours": round((g["playtime_seconds"] or 0) / 3600, 1),
            "path": g["path"], "tags": tags,
            "description": (g["description"] or "")[:400],
        }

    def _tool_stats(self, args):
        return {
            "total": self._db.query_one("SELECT COUNT(*) c FROM games")["c"],
            "confirmed": self._db.query_one("SELECT COUNT(*) c FROM games WHERE status=2")["c"],
            "pending": self._db.query_one("SELECT COUNT(*) c FROM games WHERE status=1")["c"],
            "playtime_hours": round(self._db.query_one(
                "SELECT COALESCE(SUM(playtime_seconds),0) s FROM games")["s"] / 3600, 1),
            "favorites": self._db.query_one("SELECT COUNT(*) c FROM games WHERE favorite=1")["c"],
            "makers": self._db.query_one(
                "SELECT COUNT(DISTINCT maker) c FROM games WHERE maker IS NOT NULL AND maker!=''")["c"],
        }

    def _tool_facets(self, args):
        tags = [r["name"] for r in self._db.query(
            "SELECT t.name, COUNT(*) c FROM tags t JOIN game_tags gt ON t.id=gt.tag_id"
            " GROUP BY t.id ORDER BY c DESC LIMIT 30")]
        makers = [r["maker"] for r in self._db.query(
            "SELECT maker FROM games WHERE maker IS NOT NULL AND maker!=''"
            " GROUP BY maker ORDER BY COUNT(*) DESC LIMIT 30")]
        return {"tags": tags, "makers": makers}

    def _search_provider_kw(self, kw):
        """单关键词搜 vndb+bgm（带 TTL 缓存）。"""
        from .providers import bgm, vndb
        import time as _t
        hit = self._prov_cache.get(kw)
        if hit and _t.time() - hit[0] < 300:
            return hit[1]
        out = []
        try:
            cands, err = vndb.search(self._cfg, kw, limit=3)
            for c in cands:
                out.append({"provider": "vndb", "id": c["external_id"],
                            "title": c.get("title"), "title_jp": c.get("title_orig"),
                            "maker": c.get("maker"), "released": c.get("released"),
                            "cover_url": c.get("cover_url"), "tags": c.get("tags", [])[:6],
                            "summary": (c.get("summary") or "")[:150]})
        except Exception:
            pass
        try:
            for c in bgm.search(self._cfg, kw, limit=3):
                out.append({"provider": "bgm", "id": c["external_id"],
                            "title": c.get("title"), "title_jp": c.get("title_orig"),
                            "maker": c.get("maker"), "released": c.get("released"),
                            "cover_url": c.get("cover_url"), "tags": c.get("tags", [])[:6],
                            "summary": (c.get("summary") or "")[:150]})
        except Exception:
            pass
        result = {"count": len(out), "results": out}
        self._prov_cache[kw] = (_t.time(), result)
        return result

    def _tool_search_providers(self, args):
        """搜索词变体展开：全名没结果就试 去副标题/去版本号/拆词 后的短名。"""
        kw = (args.get("keyword") or "").strip()
        if not kw:
            return {"error": "缺少关键词"}
        from .enrich import _expand_keys
        keywords = []
        for v in _expand_keys(kw):
            if v and v not in keywords:
                keywords.append(v)
        result = {"count": 0, "results": []}
        for k in keywords[:5]:
            result = self._search_provider_kw(k)
            if result["count"]:
                return result
        return result

    def _tool_update_game(self, args):
        gid = int(args.get("id"))
        fields = {k: v for k, v in args.items() if k != "id" and v is not None}
        if not fields:
            return {"error": "没有可更新的字段"}
        r = self._api.update_game(gid, fields)
        if not r.get("ok"):
            return {"error": r.get("error", "更新失败")}
        g = r["game"]
        return {"ok": True,
                "_summary": f"已修正《{g.get('title')}》",
                "updated": {k: v for k, v in fields.items()},
                "title": g.get("title"), "maker": g.get("maker"),
                "released": g.get("released")}

    def _tool_set_cover(self, args):
        url = (args.get("url") or "").strip()
        if not url.startswith("http"):
            return {"error": "URL 无效"}
        r = self._api.set_cover_url(int(args.get("id")), url)
        if not r.get("ok"):
            return {"error": r.get("error", "换封面失败")}
        return {"ok": True, "_summary": "封面已更新"}

    def _tool_reanalyze(self, args):
        r = self._api.reanalyze_game(int(args.get("id")))
        if not r.get("ok"):
            return {"error": r.get("error", "启动分析失败")}
        return {"ok": True, "_summary": "已触发后台重新分析，稍候可见结果"}

    def _tool_correct_game(self, args):
        """透传用户给的正确信息（correct_game 与 update_game_info 同实现，语义更明确）。"""
        return self._tool_update_game(args)

    _TOOL_FN = {
        "search_games": _tool_search_games,
        "get_game": _tool_get_game,
        "get_library_stats": _tool_stats,
        "list_facets": _tool_facets,
        "search_providers": _tool_search_providers,
        "correct_game": _tool_correct_game,
        "update_game_info": _tool_update_game,
        "set_game_cover": _tool_set_cover,
        "reanalyze_game": _tool_reanalyze,
    }

    # ---------- 对话主循环 ----------
    @staticmethod
    def _needs_action(message, actions):
        """用户消息含修改意图，但还没有调用任何写操作工具。"""
        if any(a["name"] in ("update_game_info", "correct_game", "set_game_cover") for a in actions):
            return False
        hints = ("搞错", "不对", "修正", "改一下", "改成", "更新", "错了", "应该是", "不是", "改回", "改名为")
        return any(h in (message or "") for h in hints)

    def chat(self, message, context_game_id=None, history=None):
        from .providers import llm
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context_game_id:
            g = self._db.query_one("SELECT title FROM games WHERE id=?", (int(context_game_id),))
            if g:
                msgs[0]["content"] += (
                    f"\n当前用户正在查看的游戏：《{g['title']}》（id={context_game_id}）。"
                    "用户提到「这个游戏」时默认指它。")
        for m in (history or [])[-12:]:
            msgs.append({"role": m.get("role") or "user", "content": m.get("content") or ""})
        msgs.append({"role": "user", "content": message})

        actions = []
        import time as _t
        last_pair = None
        compliance_tried = False
        REMINDER = ("注意：用户要求修正游戏资料，但你还没有调用任何修改工具。"
                    "请立即调用 update_game_info 或 set_game_cover 真正完成修改，然后简短告知结果。")
        for _round in range(6):
            resp, err = llm.chat_tools(self._cfg, msgs, TOOLS)
            if err:
                msg = str(err)
                if "429" in msg or "速率" in msg:
                    return {"reply": "管家被限速了（接口有每分钟次数限制），请稍等十几秒再问我～", "actions": actions}
                return {"reply": f"管家这边网络开小差了：{err}", "actions": actions}
            try:
                msg = resp["choices"][0]["message"]
            except Exception:
                return {"reply": "管家没听懂，请再说一次？", "actions": actions}
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                # 合规检查：用户要求修改但没改 → 提醒后强制再来一轮
                if not compliance_tried and self._needs_action(message, actions):
                    compliance_tried = True
                    msgs.append({"role": "user", "content": REMINDER})
                    continue
                return {"reply": (msg.get("content") or "").strip() or "(空回复)", "actions": actions}
            # 防重复空转：同一轮工具组合与上一轮完全相同 → 强制收尾（基于已有信息直接回答）
            pair = [(tc.get("function", {}).get("name", ""),
                     tc.get("function", {}).get("arguments", "")) for tc in tool_calls]
            if pair == last_pair:
                if not compliance_tried and self._needs_action(message, actions):
                    compliance_tried = True
                    msgs.append({"role": "user", "content": REMINDER})
                    continue
                msgs.append({"role": "user",
                             "content": "请基于已获得的信息直接给出最终回答，不要再调用工具。"})
                resp2, err2 = llm.chat_tools(self._cfg, msgs, TOOLS,
                                             tool_choice="none", timeout=60)
                if err2:
                    return {"reply": f"管家这边网络开小差了：{err2}", "actions": actions}
                try:
                    content = resp2["choices"][0]["message"].get("content") or ""
                except Exception:
                    content = ""
                return {"reply": content.strip() or "资料已经查得差不多，麻烦你说得更具体一点？",
                        "actions": actions}
            last_pair = pair
            msgs.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": tool_calls})
            for tc in tool_calls:
                name = tc.get("function", {}).get("name", "")
                try:
                    args = json.loads(tc.get("function", {}).get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                fn = self._TOOL_FN.get(name)
                if not fn:
                    result = {"error": f"未知工具 {name}"}
                else:
                    try:
                        result = fn(args)
                    except Exception as e:
                        result = {"error": f"{type(e).__name__}: {e}"}
                summary = result.pop("_summary", None)
                actions.append({"name": name, "args": args, "summary": summary})
                content = json.dumps(result, ensure_ascii=False, default=str)[:2500]
                msgs.append({"role": "tool", "tool_call_id": tc.get("id"), "content": content})
                _t.sleep(0.8)  # 节流，避免撞中转限速
        return {"reply": "管家有点忙不过来，麻烦再说一次？", "actions": actions}
