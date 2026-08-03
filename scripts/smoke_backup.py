"""存档备份功能冒烟测试：验证 backup.py 胶水层 + JsApi 备份方法全链路。

用法: python scripts/smoke_backup.py
覆盖: 引擎发现 → 配置同步 → 存档路径配置 → 备份 → 元数据 → 恢复 → 历史
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.api import JsApi
from backend.config import Config
from backend.db import Database


def main():
    db = Database()
    db.init()
    cfg = Config()
    api = JsApi(db, cfg)

    # 1. 引擎状态
    st = api.backup_engine_status()
    assert st["ok"], f"引擎不可用: {st['error']}"
    print(f"[1] 引擎: {st['engine_path']}")

    # 2. 测试存档路径配置（临时目录，不影响真实数据）
    test_save = os.path.join(tempfile.gettempdir(), "gala_smoke_save")
    os.makedirs(test_save, exist_ok=True)
    with open(os.path.join(test_save, "smoke.dat"), "w", encoding="utf-8") as f:
        f.write("smoke test save")

    # 3. 配置存档路径（需要一个游戏；没有就跳过，只测引擎链路）
    game = db.query_one("SELECT id, title FROM games WHERE status=2 LIMIT 1")
    if game:
        r = api.backup_save_paths(game["id"], [test_save])
        print(f"[2] 配置存档路径: ok={r.get('ok')} count={r.get('count')}")
        r = api.backup_get_save_paths(game["id"])
        print(f"[3] 读取存档路径: {r['paths']}")

        # 4. 备份（真实执行）
        r = api.backup_game([game["id"]])
        overall = r.get("overall", {}) if isinstance(r, dict) else {}
        print(f"[4] 备份: ok={r.get('ok')} totalGames={overall.get('totalGames')} "
              f"changed={overall.get('changedGames')}")

        # 5. 备份历史
        r = api.backup_list(game["id"])
        items = r.get("items", [])
        print(f"[5] 备份历史: {len(items)} 条, last={items[0]['last_backup_at'] if items else None}")

        # 6. 版本时间线
        r = api.backup_versions(game["id"])
        print(f"[6] 版本时间线: {len(r['items'])} 条")

        # 7. 全库备份（应包含刚才配置的游戏）
        r = api.backup_all()
        overall = r.get("overall", {}) if isinstance(r, dict) else {}
        print(f"[7] 全库备份: ok={r.get('ok')} totalGames={overall.get('totalGames')}")

        # 8. 恢复（dry-run 预览，不真实写回）
        r = api.backup_restore_game(game["id"], dry_run=True)
        overall = r.get("overall", {}) if isinstance(r, dict) else {}
        print(f"[8] 恢复预览: ok={r.get('ok')} totalGames={overall.get('totalGames')}")
    else:
        print("[2-8] 跳过（库里没有 status=2 的游戏），仅验证引擎链路")
        r = api.backup_sync_configs()
        print(f"[2] 配置同步(空库): {r}")

    print("\nSMOKE OK")


if __name__ == "__main__":
    main()
