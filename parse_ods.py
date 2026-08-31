#!/usr/bin/env python3
"""AP Plus 변경목록(.ods) → units.json.

`Extras/SRW_APPlus_AllyChangelist.ods` 는 밸런스 패치에 동봉된 제3자 문서라
레포에 두지 않는다. verify.py 가 쓰는 units.json 은 이 스크립트로 만든다.

  python3 parse_ods.py "<...>/Extras/SRW_APPlus_AllyChangelist.ods" units.json

시트 'Robot Data' 는 한 유닛당 블록 하나이고, 열 0~17 이 원본 값,
열 20~37 이 AP Plus 값이다 (같은 표를 옆에 나란히 붙여 놓은 구조).

  행+0  유닛 이름            (열 0 과 열 20 에 동일하게)
  행+1  머리글 Base/Upgrade/Max
  행+2  HP        Base | Upgrade | Max
  행+3  EN
  행+4  Mobility                        | Move | Type | Size | Part (머리글)
  행+5  Armor                           | Move | Type | Size | Part (값)
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
}
T = "{%s}" % NS["table"]

PLUS_COL = 20          # AP Plus 표가 시작하는 열
STAT_ROWS = ((2, "HP"), (3, "EN"), (4, "MOB"), (5, "ARM"))


def read_sheet(ods_path, sheet_name):
    with zipfile.ZipFile(ods_path) as z:
        root = ET.fromstring(z.read("content.xml"))
    for tbl in root.iter(T + "table"):
        if tbl.get(T + "name") != sheet_name:
            continue
        rows = []
        for r in tbl.findall(T + "table-row"):
            rep = int(r.get(T + "number-rows-repeated", 1))
            cells = []
            for c in r.findall(T + "table-cell"):
                crep = int(c.get(T + "number-columns-repeated", 1))
                # 행 끝을 채우는 반복 셀은 실제 데이터가 아니다
                cells.extend(["".join(c.itertext())] * (1 if crep > 200 else crep))
            while cells and cells[-1] == "":
                cells.pop()
            for _ in range(1 if rep > 50 else rep):
                rows.append(cells)
        while rows and not any(rows[-1]):
            rows.pop()
        return rows
    raise SystemExit("시트를 찾을 수 없습니다: %s" % sheet_name)


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    rows = read_sheet(sys.argv[1], "Robot Data")

    def g(r, i):
        return rows[r][i] if r < len(rows) and i < len(rows[r]) else ""

    def num(s):
        s = s.replace(",", "").strip()
        return int(s) if re.fullmatch(r"-?\d+", s) else None

    units = []
    for r in range(len(rows)):
        # 유닛 블록의 시작: 이름이 원본/Plus 양쪽에 있고 바로 아래가 Base/HP
        if not (g(r, 0) and not g(r, 1) and g(r, PLUS_COL) == g(r, 0)
                and g(r + 1, 1) == "Base" and g(r + 2, 0) == "HP"):
            continue
        u = {"name": g(r, 0), "row": r}
        for off, key in STAT_ROWS:
            u["o_" + key] = num(g(r + off, 1))
            u["o_" + key + "u"] = num(g(r + off, 2))
            u["o_" + key + "m"] = num(g(r + off, 3))
            u["p_" + key] = num(g(r + off, PLUS_COL + 1))
            u["p_" + key + "u"] = num(g(r + off, PLUS_COL + 2))
            u["p_" + key + "m"] = num(g(r + off, PLUS_COL + 3))
        u["o_MOV"] = num(g(r + 5, 5))
        u["p_MOV"] = num(g(r + 5, PLUS_COL + 5))
        u["o_SIZE"] = g(r + 5, 7)
        u["o_PART"] = num(g(r + 5, 8))
        units.append(u)

    with open(sys.argv[2], "w") as f:
        json.dump(units, f, ensure_ascii=False)
    print("유닛 %d개 → %s" % (len(units), sys.argv[2]))


if __name__ == "__main__":
    main()
