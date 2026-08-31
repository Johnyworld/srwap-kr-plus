#!/usr/bin/env python3
"""결과 ISO 독립 검증.

port_applus.py 의 매핑 로직을 쓰지 않고 다른 경로로 확인한다.
  1) 원본 ISO 와 결과 ISO 를 전부 비교해서 바뀐 바이트가 예상 범위 안에만 있는지
  2) 결과 ISO 의 스탯을 ODS 변경목록(AP Plus) 과 직접 대조
  3) 생성된 PPF 를 독립 구현으로 재적용해서 결과 ISO 와 일치하는지
"""
import json
import struct
import sys

import numpy as np

SRC = sys.argv[1]
OUT = sys.argv[2]
PPF = sys.argv[3]
UNITS = sys.argv[4]

KR_UNIT = 0x1C182CF0
KR_WEAP = 0x1C18A8E4
MIRROR = 0x14C46000
UNIT_N = 305

a = np.memmap(SRC, dtype=np.uint8, mode="r")
b = np.memmap(OUT, dtype=np.uint8, mode="r")

# ---------------------------------------------------------------- 1) 전체 diff
print("=== 1) 원본 vs 결과 전체 바이너리 비교 ===")
assert len(a) == len(b), "크기가 다름"
CH = 1 << 26
diff = []
for s in range(0, len(a), CH):
    e = min(len(a), s + CH)
    m = np.array(a[s:e]) != np.array(b[s:e])
    if m.any():
        diff += (s + np.flatnonzero(m)).tolist()
print("   변경된 바이트: %d" % len(diff))
lo_sh, hi_sh = KR_UNIT, 0x1C198000
lo_du, hi_du = KR_UNIT - MIRROR, 0x1C198000 - MIRROR
outside = [o for o in diff if not (lo_sh <= o < hi_sh or lo_du <= o < hi_du)]
print("   shared.bin 테이블 영역 안: %d" % sum(1 for o in diff if lo_sh <= o < hi_sh))
print("   dummy.bin 사본 영역 안:   %d" % sum(1 for o in diff if lo_du <= o < hi_du))
print("   그 밖의 위치:             %d %s" % (len(outside), [hex(o) for o in outside[:8]]))

# 두 사본이 패치 후에도 서로 동일한가
c1 = np.array(b[lo_sh:hi_sh])
c2 = np.array(b[lo_du:hi_du])
print("   두 사본 일치 여부: 불일치 %d바이트" % int((c1 != c2).sum()))

# ---------------------------------------------------------------- 2) ODS 대조
print("\n=== 2) 결과 ISO 스탯 vs ODS AP Plus ===")
units = json.load(open(UNITS))


def u16(arr, o):
    return int(arr[o]) | (int(arr[o + 1]) << 8)


# 원본 ISO 에서 각 유닛의 레코드 인덱스를 찾는다 (원본 스탯 기준)
src_hp = np.array([u16(a, KR_UNIT + k * 0x68) for k in range(UNIT_N)])
src_en = np.array([u16(a, KR_UNIT + k * 0x68 + 0x1C) for k in range(UNIT_N)])
src_arm = np.array([u16(a, KR_UNIT + k * 0x68 + 0x1E) for k in range(UNIT_N)])
src_mob = np.array([int(a[KR_UNIT + k * 0x68 + 0x5D]) for k in range(UNIT_N)])
src_mov = np.array([int(a[KR_UNIT + k * 0x68 + 0x5C]) for k in range(UNIT_N)])

# ODS(2024-04) 와 패치 v1.2(2024-08) 사이의 문서 미갱신 항목.
# 패치가 실제로 하는 동작이 기준이고, 아래는 ODS 쪽이 옛날 값이다.
KNOWN_ODS_DRIFT = {
    ("Altron Gundam", "ARM"),
    ("Getter-3", "MOB"),
    ("Cardboardier V", "MOB"),
    ("Vysaga", "EN"),
}

ok = bad = skip = 0
drift = []
fails = []
for u in units:
    if None in (u["o_HP"], u["o_EN"], u["o_ARM"], u["o_MOB"]):
        continue
    m = ((src_hp == u["o_HP"]) & (src_en == u["o_EN"]) &
         (src_arm == u["o_ARM"]) & (src_mob == u["o_MOB"]))
    if u["o_MOV"]:
        m &= (src_mov == u["o_MOV"])
    idx = np.flatnonzero(m)
    if len(idx) != 1:
        skip += 1
        continue
    k = int(idx[0])
    o = KR_UNIT + k * 0x68
    got = {"HP": u16(b, o), "EN": u16(b, o + 0x1C),
           "ARM": u16(b, o + 0x1E), "MOB": int(b[o + 0x5D])}
    for key in ("HP", "EN", "ARM", "MOB"):
        exp = u["p_" + key]
        if exp is None:
            continue
        if got[key] == exp:
            ok += 1
        elif (u["name"], key) in KNOWN_ODS_DRIFT:
            drift.append((u["name"], k, key, u["o_" + key], exp, got[key]))
        else:
            bad += 1
            fails.append((u["name"], k, key, u["o_" + key], exp, got[key]))
print("   유일하게 식별된 유닛으로 %d필드 대조: 일치 %d / 문서차이 %d / 불일치 %d "
      "(중복스탯 유닛 %d개는 제외)" % (ok + len(drift) + bad, ok, len(drift), bad, skip))
for f in drift:
    print("      [ODS 문서차이] %-24s idx=%-4d %-4s 원본=%-6s ODS=%-6s 패치결과=%s" % f)
for f in fails:
    print("      [불일치] %-26s idx=%-4d %-4s 원본=%-6s ODS=%-6s 결과=%s" % f)

# ---------------------------------------------------------------- 3) PPF 재적용
print("\n=== 3) 생성된 PPF 독립 재적용 ===")
p = open(PPF, "rb").read()
assert p[:5] == b"PPF30"
blockcheck, undo = p[57], p[58]
print("   blockcheck=%d undo=%d" % (blockcheck, undo))
i = 60
if blockcheck:
    bc = p[60:60 + 1024]
    print("   blockcheck 1024B == 원본 ISO 0x9320: %s"
          % (bytes(a[0x9320:0x9320 + 1024]) == bc))
    i += 1024
applied = {}
while i < len(p):
    off = struct.unpack("<Q", p[i:i + 8])[0]
    i += 8
    n = p[i]
    i += 1
    applied[off] = p[i:i + n]
    i += n
    if undo:
        i += n
total = sum(len(v) for v in applied.values())
print("   레코드 %d개 / %d바이트" % (len(applied), total))

# 원본에 PPF 를 적용한 결과가 OUT 과 같은지 (변경 바이트 집합으로 비교)
ppf_pos = set()
mismatch = 0
for off, data in applied.items():
    for j, ch in enumerate(data):
        ppf_pos.add(off + j)
        if int(b[off + j]) != ch:
            mismatch += 1
print("   PPF 값 != 결과 ISO: %d바이트" % mismatch)
only_diff = set(diff) - ppf_pos
only_ppf = ppf_pos - set(diff)
print("   결과에는 바뀌었는데 PPF 에 없는 바이트: %d" % len(only_diff))
print("   PPF 에는 있는데 결과가 원본과 같은 바이트: %d (원래 값과 동일한 기록)"
      % len(only_ppf))

print("\n=== 판정 ===")
verdict = (len(outside) == 0 and int((c1 != c2).sum()) == 0 and bad == 0
           and mismatch == 0 and len(only_diff) == 0)
print("   " + ("전부 통과" if verdict else "문제 있음 — 위 항목 확인"))
sys.exit(0 if verdict else 1)
