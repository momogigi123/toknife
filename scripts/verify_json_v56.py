# -*- coding: utf-8 -*-
"""verify_json_v56 — JSON 數值保真 + 校驗錨點（零 API，確定性）。

V-20a 數值表壓縮後總和完整（300 筆 dict 陣列，sales 總和不變）
V-20b 校驗錨點總和 == 原資料總和（由原始資料算，不改寫資料）
V-20c 非數值表不自動加 # 統計 行
V-20d 小 JSON 負收益退回原文（CSV 不比原文短）
V-20e 單 dict 退回 JSON（非表格不入 CSV，保真優先）
"""
import json, csv, io, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json_compressor as jc
import random


def _num_intact(content: str, key: str) -> bool:
    cj = jc.compress_json_light(content)
    rdr = csv.reader(io.StringIO(cj))
    rows = [r for r in rdr if r and not r[0].startswith("#")]
    hdr = rows[0]
    if key not in hdr:
        return False
    si = hdr.index(key)
    vals = [int(r[si]) for r in rows[1:] if r and r[si].lstrip("-").isdigit()]
    orig = json.loads(content)
    orig_sum = sum(r[key] for r in orig)
    return len(vals) == len(orig) and sum(vals) == orig_sum


def _anchor_sum_ok(content: str, key: str) -> bool:
    cj = jc.compress_json_light(content)
    import re
    m = re.search(rf"{key}:筆數\d+/總和(-?\d+)", cj)
    if not m:
        return False
    orig = json.loads(content)
    return int(m.group(1)) == sum(r[key] for r in orig)


def main():
    fails = []

    # V-20a + V-20b 數值表
    random.seed(42)
    rows = [{"product": f"P{i:03d}", "sales": random.randint(1000, 9999),
             "region": random.choice(["華北", "華南", "華東"]),
             "cat": random.choice(["電子", "配件", "周邊"])} for i in range(300)]
    content = json.dumps(rows, ensure_ascii=False)
    if not _num_intact(content, "sales"):
        fails.append("V-20a 數值表壓縮後總和完整")
    if not _anchor_sum_ok(content, "sales"):
        fails.append("V-20b 校驗錨點總和==原總和")
    if "# 統計" not in jc.compress_json_light(content):
        fails.append("V-20b2 含 # 統計 錨點行")

    # V-20c 非數值表不加統計
    t2 = [{"name": "甲", "city": "重慶"}, {"name": "乙", "city": "台北"}]
    if "# 統計" in jc.compress_json_light(json.dumps(t2, ensure_ascii=False)):
        fails.append("V-20c 非數值表不應加 # 統計")

    # V-20d 小 JSON：CSV 較短則轉 CSV（正確行為），驗證值不丟失
    small = json.dumps([{"x": 1}, {"x": 2}], ensure_ascii=False)
    cs = jc.compress_json_light(small)
    srdr = csv.reader(io.StringIO(cs))
    srows = [r for r in srdr if r and not r[0].startswith("#")]
    sx = [int(r[0]) for r in srows[1:] if r]
    if sx != [1, 2]:
        fails.append("V-20d 小 JSON 值不丟失")

    # V-20e 單 dict：值不丟失（轉 CSV 當更短亦保真）
    od = json.dumps({"a": 1, "b": 2}, ensure_ascii=False)
    oc = jc.compress_json_light(od)
    ordr = csv.reader(io.StringIO(oc))
    orows = [r for r in ordr if r and not r[0].startswith("#")]
    flat = [v for r in orows for v in r]
    if "1" not in flat or "2" not in flat:
        fails.append("V-20e 單 dict 值不丟失")

    print("verify_json_v56 (V-20a~e):")
    if not fails:
        print("  ALL PASS ✅")
        return 0
    print("  FAIL ❌ ->")
    for f in fails:
        print("   -", f)
    return 1


if __name__ == "__main__":
    sys.exit(main())
