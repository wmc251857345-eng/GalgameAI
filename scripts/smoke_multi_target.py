"""多目标备份实测：U盘 + OneDrive 双线。"""
import sys, os, json, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import Config
from backend.db import Database
from backend.api import JsApi

db = Database(); db.init()
cfg = Config()
api = JsApi(db, cfg)

ts = "gala_save_test"
targets = [
    {"path": os.path.join("I:\\", ts), "enabled": True, "label": "U盘测试"},
    {"path": os.path.join("D:\\OneDrive", ts), "enabled": True, "label": "OneDrive测试"},
]
r = api.backup_set_targets(targets)
print("[设置目标] ok:", r["ok"])
for t in r["targets"]:
    print("   ", t["kind"], "|", t["path"], "| enabled:", t["enabled"])

# 造测试存档
test_save = os.path.join(tempfile.gettempdir(), "gala_multi_save")
os.makedirs(test_save, exist_ok=True)
with open(os.path.join(test_save, "save1.dat"), "w") as f:
    f.write("MULTI TARGET TEST")

# 配置到魔导巧壳(id=3)
api.backup_save_paths(3, [test_save])

# 全库多目标备份
r = api.backup_all()
print("[多目标备份] ok:", r.get("ok"), "| error:", r.get("error"))
for t in r.get("targets", []):
    ov = t.get("overall") or {}
    print("   ", t["label"], "| ok:", t["ok"], "| games:", ov.get("totalGames"),
          "| bytes:", ov.get("totalBytes"), "| error:", t.get("error"))

# 验证文件确实写入了两个目标
for p in (os.path.join("I:\\", ts), os.path.join("D:\\OneDrive", ts)):
    found = []
    for root, dirs, files in os.walk(p):
        for fn in files:
            found.append(os.path.join(root, fn))
    print("[验证]", p, "→", len(found), "个文件")
