"""CLI 参数解析安全项：未知参数必须报错，禁止静默忽略（切片3）。"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_analyze_swing_unknown_arg_raises():
    """analyze_swing 未知 -- 参数抛 ValueError，不静默跳过。"""
    from scripts.analyze_swing import parse_args
    import pytest

    sys.argv = ["analyze_swing.py", "600000", "--stratgy", "band"]
    with pytest.raises(ValueError, match="未知参数"):
        parse_args()


def test_analyze_unknown_arg_exits_nonzero():
    """analyze.py 未知 -- 参数 exit 1 并提示（不拉网络，秒退）。"""
    p = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "analyze.py"), "600000", "--jso"],
        capture_output=True, text=True, timeout=30)
    assert p.returncode == 1
    assert "未知参数" in p.stderr + p.stdout


def test_json_safe_cuts_circular_reference():
    """_json_safe 剪断循环引用，输出可 json.dumps。"""
    from scripts.analyze import _json_safe

    a = {"x": 1}
    a["self"] = a  # 环
    b = [a, a]     # DAG 重复引用（非环）
    out = _json_safe(b)
    assert json.dumps(out)  # 不抛
    assert out[0]["x"] == 1
    assert out[0]["self"] == "<circular>"
    assert out[1] == out[0]  # 重复引用保留（非环）


def test_json_safe_object_to_dict_summary():
    """任意对象转非私有属性 dict 摘要。"""
    from scripts.analyze import _json_safe

    class Obj:
        def __init__(self):
            self.date = "2026-09-18"
            self._internal = {"secret": 1}

    out = _json_safe(Obj())
    assert out == {"date": "2026-09-18"}


def test_trendgate_pool_hsi_help():
    """backtest_trendgate --pool hsi 参数已注册（2026-10-13 恒指成分池）。"""
    import subprocess, sys
    p = subprocess.run([sys.executable, "scripts/backtest_trendgate.py", "--help"],
                       capture_output=True, text=True, timeout=30)
    assert p.returncode == 0
    assert "--pool" in p.stdout
    assert "hsi" in p.stdout


def test_fetch_hsi_constituents_cache_valid():
    """恒指成分池缓存 universe_hk_hsi.json 结构合法（93 只左右、5 位港股代码）。"""
    import json
    from pathlib import Path
    f = Path("data/rotation_cache/universe_hk_hsi.json")
    if not f.exists():
        import pytest
        pytest.skip("无恒指成分缓存（需联网拉维基后写入）")
    uni = json.loads(f.read_text(encoding="utf-8"))
    assert len(uni) > 80
    assert all(u.get("market") == "hk" and len(str(u.get("code", ""))) == 5 for u in uni)
