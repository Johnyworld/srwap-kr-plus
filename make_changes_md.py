#!/usr/bin/env python3
"""AP Plus 1.2 변경사항 문서(CHANGES.md) 생성기.

변경 내용 자체는 밸런스 패치에 동봉된 변경목록(.ods) 에서 읽고,
실제로 그 값이 들어갔는지는 원본 ISO 와 패치된 ISO 를 직접 비교해서 확인한다.
ODS 는 2024-04, 패치 본체는 2024-08(v1.2) 이라 어긋나는 항목이 몇 개 있는데
그건 ISO 쪽 값을 기준으로 표시한다.

  python3 make_changes_md.py <변경목록.ods> <원본ISO> <패치ISO> CHANGES.md
"""
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"

KR_UNIT = 0x1C182CF0
UNIT_N = 305
UNIT_SZ = 0x68

ROBOT_PLUS = 20        # Robot Data 시트에서 AP Plus 표가 시작하는 열
PILOT_PLUS = 22        # Pilot Data 시트

STATS = (("HP", 2), ("EN", 3), ("Mobility", 4), ("Armor", 5))
STAT_KR = {"HP": "HP", "EN": "EN", "Mobility": "운동성", "Armor": "장갑"}
# ISO 유닛 레코드에서 검증 가능한 필드
ISO_FIELD = {"HP": (0x00, 2), "EN": (0x1C, 2), "Armor": (0x1E, 2), "Mobility": (0x5D, 1)}

WCOLS = (("Type", 1), ("Att", 2), ("Base Pow", 3), ("Max", 4), ("Rng", 5),
         ("EN", 6), ("Am", 7), ("Hit", 8), ("Cri", 9), ("Will", 10),
         ("Air", 11), ("Lnd", 12), ("Wtr", 13), ("Spc", 14),
         ("Parry", 15), ("Jam", 16), ("Other", 17))
WCOL_KR = {"Type": "종류", "Att": "속성", "Base Pow": "파워", "Max": "최대",
           "Rng": "사거리", "EN": "EN", "Am": "탄수", "Hit": "명중", "Cri": "크리",
           "Will": "기력", "Air": "공", "Lnd": "육", "Wtr": "수", "Spc": "우주",
           "Parry": "무기방어", "Jam": "재밍", "Other": "기타"}


# ------------------------------------------------------------------ ODS 읽기

def read_sheet(ods, name):
    with zipfile.ZipFile(ods) as z:
        root = ET.fromstring(z.read("content.xml"))
    for tbl in root.iter(T + "table"):
        if tbl.get(T + "name") != name:
            continue
        rows = []
        for r in tbl.findall(T + "table-row"):
            rep = int(r.get(T + "number-rows-repeated", 1))
            cells = []
            for c in r.findall(T + "table-cell"):
                crep = int(c.get(T + "number-columns-repeated", 1))
                cells.extend(["".join(c.itertext())] * (1 if crep > 200 else crep))
            while cells and cells[-1] == "":
                cells.pop()
            for _ in range(1 if rep > 50 else rep):
                rows.append(cells)
        while rows and not any(rows[-1]):
            rows.pop()
        return rows
    raise SystemExit("시트 없음: %s" % name)


def cell(rows, r, i):
    return rows[r][i] if 0 <= r < len(rows) and i < len(rows[r]) else ""


def num(s):
    s = str(s).replace(",", "").strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else None


# ------------------------------------------------------------------ 파싱

def parse_robots(rows):
    out = []
    for r in range(len(rows)):
        # 블록 앵커는 표 구조로만 잡는다. 이름이 Plus 열에 안 적혀 있거나 (George De
        # Sand 등) 이름 행에 다른 값이 끼어 있는 (Kou Uraki 의 '70') 경우가 있어서
        # 이름 위치로 앵커를 잡으면 블록을 놓친다.
        if not (cell(rows, r, 0) and cell(rows, r + 1, 1) == "Base"
                and cell(rows, r + 2, 0) == "HP" and cell(rows, r + 3, 0) == "EN"
                and cell(rows, r + 5, 0) == "Armor"):
            continue
        P = ROBOT_PLUS
        u = {"name": cell(rows, r, 0), "row": r, "stats": {}, "extra": {}}
        for key, off in STATS:
            u["stats"][key] = {
                "o": [cell(rows, r + off, 1), cell(rows, r + off, 2), cell(rows, r + off, 3)],
                "p": [cell(rows, r + off, P + 1), cell(rows, r + off, P + 2),
                      cell(rows, r + off, P + 3)],
            }
        u["extra"]["지형(공/육/수/우주)"] = (
            "/".join(cell(rows, r + 2, c) for c in (5, 6, 7, 8)),
            "/".join(cell(rows, r + 2, P + c) for c in (5, 6, 7, 8)))
        u["extra"]["이동력"] = (cell(rows, r + 5, 5), cell(rows, r + 5, P + 5))
        u["extra"]["타입"] = (cell(rows, r + 5, 6), cell(rows, r + 5, P + 6))
        u["extra"]["크기"] = (cell(rows, r + 5, 7), cell(rows, r + 5, P + 7))
        u["extra"]["파츠 슬롯"] = (cell(rows, r + 5, 8), cell(rows, r + 5, P + 8))

        # 능력 / FUB / 무기
        wh = None
        abil_o, abil_p = [], []
        for k in range(6, 40):
            if cell(rows, k + r, 1) == "Type":
                wh = r + k
                break
            if cell(rows, r + k, 2) == "FUB":
                u["extra"]["FUB 비용"] = (cell(rows, r + k, 3), cell(rows, r + k, P + 3))
            for c, acc in ((0, abil_o), (2, abil_o), (P, abil_p), (P + 2, abil_p)):
                v = cell(rows, r + k, c)
                if v and v not in ("Abilities", "FUB"):
                    acc.append(v)
            if cell(rows, r + k, 16) or cell(rows, r + k, P + 16):
                u["extra"][cell(rows, r + k, 16) or "기타"] = (
                    cell(rows, r + k, 17), cell(rows, r + k, P + 17))
        u["abil"] = (abil_o, abil_p)

        weapons_o, weapons_p = [], []
        if wh:
            k = wh + 1
            while k < len(rows) and (cell(rows, k, 0) or cell(rows, k, P)):
                if cell(rows, k, 0):
                    weapons_o.append((cell(rows, k, 0),
                                      {n: cell(rows, k, c) for n, c in WCOLS}))
                if cell(rows, k, P):
                    weapons_p.append((cell(rows, k, P),
                                      {n: cell(rows, k, P + c) for n, c in WCOLS}))
                k += 1
        u["weapons"] = (weapons_o, weapons_p)
        out.append(u)
    return out


def parse_pilot_half(rows, base):
    """파일럿 표의 한쪽 반만 읽는다. base=0 이면 원본, base=PILOT_PLUS 면 AP Plus.

    두 반쪽은 행이 항상 맞지 않는다. Plus 쪽 정신기/스킬 줄 수가 달라서 한 행씩
    밀린 블록이 6개 있다 (George De Sand, Sai Saici, Duo Maxwell, Zechs Marquise,
    Lucrezia Noin, 그리고 한 행 앞선 블록 하나). 그래서 각 반쪽을 독립적으로
    앵커링한 뒤 순서대로 짝지어야 한다.
    """
    anchors = [s for s in range(len(rows)) if cell(rows, s, base) == "SP Cost"]
    out = []
    for i, s in enumerate(anchors):
        stop = (anchors[i + 1] - 2) if i + 1 < len(anchors) else len(rows)
        h = {"row": s}
        h["name"] = cell(rows, s - 1, base) or cell(rows, s - 2, base)
        h["spirits"] = [cell(rows, s - 1, base + c) for c in range(1, 7)]
        h["sp"] = [cell(rows, s, base + c) for c in range(1, 7)]
        lv = next((s + k for k in range(1, 4)
                   if cell(rows, s + k, base) == "Level"), s + 1)
        h["lv"] = [cell(rows, lv, base + c) for c in range(1, 7)]
        h["terrain"] = ""
        h["skills"] = []
        h["basesp"] = ""
        h["growth"] = {}
        for k in range(0, 10):
            r = s + k
            if r >= stop:
                break
            if cell(rows, r, base) == "Terrain" and not h["terrain"]:
                h["terrain"] = "/".join(cell(rows, r, base + c) for c in range(1, 5))
            n = cell(rows, r, base + 9)
            if n:
                h["skills"].append(
                    (n, [cell(rows, r, base + c) for c in range(10, 19)]))
            if cell(rows, r, base + 5) == "Base SP":
                h["basesp"] = cell(rows, r, base + 6)
            v = cell(rows, r, base + 5)
            if v in ("10", "30"):
                h["growth"][v] = cell(rows, r, base + 6)
        out.append(h)
    return out


def parse_pilots(rows):
    lo = parse_pilot_half(rows, 0)
    lp = parse_pilot_half(rows, PILOT_PLUS)
    if len(lo) != len(lp):
        raise SystemExit("원본/Plus 파일럿 블록 수가 다릅니다: %d vs %d"
                         % (len(lo), len(lp)))
    out = []
    for x, y in zip(lo, lp):
        name = x["name"]
        if y["name"] and y["name"] != name:
            name = "%s (문서 Plus 표기: %s)" % (name, y["name"])
        keys = set(x["growth"]) | set(y["growth"])
        out.append({
            "name": name, "row": x["row"],
            "spirits": (x["spirits"], y["spirits"]),
            "sp": (x["sp"], y["sp"]),
            "lv": (x["lv"], y["lv"]),
            "terrain": (x["terrain"], y["terrain"]),
            "skills": (x["skills"], y["skills"]),
            "basesp": (x["basesp"], y["basesp"]),
            "growth": {k: (x["growth"].get(k, ""), y["growth"].get(k, ""))
                       for k in keys},
        })
    return out


# ------------------------------------------------------------------ ISO 검증

def build_iso_index(a):
    """원본 ISO 유닛 레코드를 (HP,EN,장갑,운동성,이동) 로 색인."""
    def u16(o):
        return int(a[o]) | (int(a[o + 1]) << 8)
    idx = {}
    for k in range(UNIT_N):
        o = KR_UNIT + k * UNIT_SZ
        key = (u16(o), u16(o + 0x1C), u16(o + 0x1E), int(a[o + 0x5D]), int(a[o + 0x5C]))
        idx.setdefault(key, []).append(k)
    return idx


def _rd(arr, k):
    def u16(o):
        return int(arr[o]) | (int(arr[o + 1]) << 8)
    o = KR_UNIT + k * UNIT_SZ
    return (u16(o), u16(o + 0x1C), u16(o + 0x1E), int(arr[o + 0x5D]))


def verify(u, idx, a, b):
    """ODS 의 Plus 값이 패치 ISO 에 실제로 들어갔는지 확인한다.
    유닛이 원본 스탯으로 유일하게 식별될 때만 검사한다.

    반환 (종류, 상세):
      ("unverified", None)  스탯이 다른 유닛과 겹쳐 식별 불가
      ("ok", None)          ODS Plus 값이 그대로 들어갔다
      ("drift", {필드: 실제값})
                            ODS Plus 값과 실제 패치가 다르다 (문서가 구버전)
      ("ods_orig_error", (잘못된idx, 실제idx, 실제원본))
                            ODS 원본 열이 다른 기체(적 버전 등) 수치를 적어놨다.
                            매칭된 레코드는 패치가 건드리지 않았고, ODS Plus 값과
                            정확히 일치하게 바뀐 다른 레코드가 딱 하나 있는 경우.
    """
    okey = (num(u["stats"]["HP"]["o"][0]), num(u["stats"]["EN"]["o"][0]),
            num(u["stats"]["Armor"]["o"][0]), num(u["stats"]["Mobility"]["o"][0]),
            num(u["extra"]["이동력"][0]))
    ks = idx.get(okey, [])
    if len(ks) != 1:
        return "unverified", None
    k = ks[0]
    want = tuple(num(u["stats"][n]["p"][0])
                 for n in ("HP", "EN", "Armor", "Mobility"))
    got = _rd(b, k)
    if all(w is None or w == g for w, g in zip(want, got)):
        return "ok", None

    if _rd(a, k) == got:                       # 매칭된 레코드는 아예 안 바뀌었다
        alt = [j for j in range(UNIT_N)
               if _rd(b, j) == want and _rd(a, j) != _rd(b, j)]
        if len(alt) == 1:
            return "ods_orig_error", (k, alt[0], _rd(a, alt[0]))

    names = ("HP", "EN", "Armor", "Mobility")
    return "drift", {n: g for n, w, g in zip(names, want, got) if w is not None and w != g}


# ------------------------------------------------------------------ 출력 도우미

def arrow(o, p):
    o, p = (o or "-").strip(), (p or "-").strip()
    return None if o == p else "%s → **%s**" % (o, p)


def md_table(head, rows):
    if not rows:
        return "변경 없음.\n"
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join(["---"] * len(head)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) if str(x) else "" for x in r) + " |")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ 본문

def main():
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    ods, src, out_iso, dest = sys.argv[1:5]
    rr = read_sheet(ods, "Robot Data")
    pr = read_sheet(ods, "Pilot Data")
    robots = parse_robots(rr)
    pilots = parse_pilots(pr)
    a = np.memmap(src, dtype=np.uint8, mode="r")
    b = np.memmap(out_iso, dtype=np.uint8, mode="r")
    idx = build_iso_index(a)

    drift = []          # ODS Plus 열이 구버전인 항목
    ods_err = []        # ODS 원본 열이 다른 기체 수치를 적어놓은 항목
    verified = unver = 0

    L = []
    L.append("# AP Plus 1.2 변경사항")
    L.append("")
    L.append("**Super Robot Wars A Portable Plus v1.2** (Super Rebalance Wars Team) 가")
    L.append("바꾸는 내용 전체. 한글패치 v2.4 ISO 에 이식 적용한 결과 기준.")
    L.append("")
    L.append("변경 내용은 패치에 동봉된 `SRW_APPlus_AllyChangelist.ods` 에서 뽑았고,")
    L.append("그 값이 실제로 들어갔는지는 원본 ISO 와 패치 ISO 를 직접 비교해 확인했다.")
    L.append("`원본 → **변경값**` 형식이며 **바뀐 항목만** 싣는다.")
    L.append("")
    L.append("> 적 유닛은 v1.2 에서 손대지 않는다. 아군 로스터만 재조정한 패치다.")
    L.append("> 파일럿 스킬 습득 목록은 New Game 때 초기화되므로 **세이브를 새로 시작**해야")
    L.append("> 스킬 변경이 반영된다.")
    L.append("")
    L.append("## 0. 적용 확인 (실기)")
    L.append("")
    L.append("라미아로 새 게임을 시작해서 아래가 보이면 적용된 것이다.")
    L.append("")
    L.append(md_table(["확인 항목", "원본", "패치 후"], [
        ["Lv1 정신기 1번", "가속 (Accel)", "**필중 (Strike)**"],
        ["Lv1 정신기 2번", "집중 (Focus)", "**철벽 (Guard)**"],
        ["표시 SP (시작 시점)", "38", "**63**"],
        ["Lv8 습득 정신기", "번뜩임 (Alert)", "**돌격 (Assail)**"],
    ]))
    L.append("")
    L.append("정신기 1·2번과 SP 63 은 실기에서 확인했다. 한글판 정신기 이름은 이 확인으로")
    L.append("정신기 ID 9 = 필중, ID 12 = 철벽 인 것까지 확정된 것이고, 나머지 이름은")
    L.append("영문 표기를 그대로 뒀다.")
    L.append("")
    L.append("Axel Almer 를 주인공으로 고르면 이 확인법은 쓸 수 없다. Axel 의 1번 정신기는")
    L.append("패치 후에도 가속(Accel) 그대로다. 대신 **기본 SP 35 → 55** 를 보면 된다.")
    L.append("")

    # ---------------- 1. 유닛 기본 스탯
    base_rows = []
    upg_rows = []
    etc_rows = []
    abil_rows = []
    for u in robots:
        kind, det = verify(u, idx, a, b)
        if kind == "unverified":
            unver += 1
        elif kind == "ok":
            verified += 1
        elif kind == "ods_orig_error":
            bad_k, real_k, real_orig = det
            ods_err.append([
                u["name"],
                "%s / %s / %s / %s" % (u["stats"]["HP"]["o"][0], u["stats"]["EN"]["o"][0],
                                       u["stats"]["Armor"]["o"][0],
                                       u["stats"]["Mobility"]["o"][0]),
                "%d / %d / %d / %d" % real_orig,
                "idx %d (ODS 원본이 가리킨 것은 idx %d, 패치 미변경)" % (real_k, bad_k)])

        cells = []
        any_change = False
        for key, _ in STATS:
            o, p = u["stats"][key]["o"][0], u["stats"][key]["p"][0]
            s = arrow(o, p)
            if s and kind == "drift" and key in det:
                drift.append([u["name"], STAT_KR[key], o, p, det[key]])
                s = "%s → **%s** ⚠️" % (o, det[key])
            elif s and kind == "ods_orig_error":
                s += " ※"
            if s:
                any_change = True
            cells.append(s or "")
        mv = arrow(*u["extra"].get("이동력", ("", "")))
        if mv:
            any_change = True
        if any_change:
            base_rows.append([u["name"]] + cells + [mv or ""])

        # 개조 단계 / 최대치
        ucells = []
        ch = False
        for key, _ in STATS:
            o, p = u["stats"][key]["o"], u["stats"][key]["p"]
            s1 = arrow(o[1], p[1])
            s2 = arrow(o[2], p[2])
            part = " / ".join(x for x in (s1, s2) if x)
            ucells.append(part)
            ch = ch or bool(part)
        if ch:
            upg_rows.append([u["name"]] + ucells)

        # 기타 필드
        for k, (o, p) in u["extra"].items():
            if k == "이동력":
                continue
            s = arrow(o, p)
            if s:
                etc_rows.append([u["name"], k, s])

        ao, ap = u["abil"]
        if ao != ap:
            gone = [x for x in ao if x not in ap]
            new = [x for x in ap if x not in ao]
            if gone or new:
                abil_rows.append([u["name"],
                                  ", ".join(gone) or "-",
                                  ", ".join(new) or "-"])

    L.append("## 1. 유닛 기본 스탯")
    L.append("")
    L.append("개조 전 초기값.")
    L.append("")
    L.append("- ⚠️ ODS 문서와 실제 패치가 다른 항목. **실제 패치 값**을 적었다.")
    L.append("- ※ ODS 의 원본 열이 다른 기체(적 버전) 수치를 적어놓은 항목. 변경 후 값은 맞다.")
    L.append("  자세한 내용은 부록.")
    L.append("")
    L.append(md_table(["유닛", "HP", "EN", "운동성", "장갑", "이동력"], base_rows))
    L.append("")
    L.append("## 2. 개조 단계 수 / 최대치")
    L.append("")
    L.append("`단계수 변경 / 최대치 변경` 순서. 단계 수가 줄고 최대치가 낮아진 유닛이 많은데,")
    L.append("초기값을 올려 개조 없이도 쓸 수 있게 만든 대신 상한을 낮춘 설계다.")
    L.append("")
    L.append(md_table(["유닛", "HP", "EN", "운동성", "장갑"], upg_rows))
    L.append("")
    L.append("## 3. 유닛 능력 변경")
    L.append("")
    L.append(md_table(["유닛", "삭제", "추가"], abil_rows))
    L.append("")
    L.append("## 4. 유닛 기타 (지형·크기·파츠·FUB 비용)")
    L.append("")
    L.append(md_table(["유닛", "항목", "변경"], etc_rows))
    L.append("")

    # ---------------- 5. 무기
    wrows = []
    wlist = []
    for u in robots:
        wo, wp = u["weapons"]
        do = dict(wo)
        dp = dict(wp)
        gone = [n for n, _ in wo if n not in dp]
        new = [n for n, _ in wp if n not in do]
        if gone or new:
            wlist.append([u["name"], ", ".join(gone) or "-", ", ".join(new) or "-"])
        for name, _ in wo:
            if name not in dp:
                continue
            cells = []
            ch = False
            for cn, _ in WCOLS:
                s = arrow(do[name].get(cn, ""), dp[name].get(cn, ""))
                cells.append(s or "")
                ch = ch or bool(s)
            if ch:
                wrows.append([u["name"], name] + cells)

    keep = [i for i, (cn, _) in enumerate(WCOLS)
            if any(r[2 + i] for r in wrows)]
    head = ["유닛", "무기"] + [WCOL_KR[WCOLS[i][0]] for i in keep]
    wrows2 = [[r[0], r[1]] + [r[2 + i] for i in keep] for r in wrows]

    L.append("## 5. 무기 성능 변경")
    L.append("")
    L.append(md_table(head, wrows2))
    L.append("")
    L.append("## 6. 무기 추가 / 삭제")
    L.append("")
    L.append(md_table(["유닛", "삭제된 무기", "추가된 무기"], wlist))
    L.append("")

    # ---------------- 7. 파일럿
    sp_rows, sprt_rows, skill_rows, base_sp_rows, pter_rows = [], [], [], [], []
    for p in pilots:
        so, sp_ = p["spirits"]
        co, cp = p["sp"]
        lo, lp = p["lv"]
        for i in range(6):
            a1 = arrow(so[i], sp_[i])
            if a1:
                sprt_rows.append([p["name"], "%d번" % (i + 1), a1,
                                  "%s → %s" % (co[i] or "-", cp[i] or "-"),
                                  "%s → %s" % (lo[i] or "-", lp[i] or "-")])
        cells = []
        ch = False
        for i in range(6):
            nm = sp_[i] or so[i]
            s1 = arrow(co[i], cp[i])
            s2 = arrow(lo[i], lp[i])
            part = " / ".join(x for x in (s1, s2) if x)
            if part:
                cells.append("%s %s" % (nm, part))
                ch = True
        if ch:
            sp_rows.append([p["name"], "<br>".join(cells)])
        s = arrow(*p["basesp"])
        if s:
            # ODS 는 Plus 쪽 Lv10/Lv30 값을 적어두지 않았다. 원본 값만 참고로 싣는다.
            base_sp_rows.append([p["name"], s,
                                 p["growth"].get("10", ("", ""))[0] or "",
                                 p["growth"].get("30", ("", ""))[0] or ""])
        s = arrow(*p["terrain"])
        if s:
            pter_rows.append([p["name"], s])
        ko, kp = p["skills"]
        dko, dkp = dict(ko), dict(kp)
        for nm in [n for n, _ in ko] + [n for n, _ in kp if n not in dko]:
            ov = "/".join(x for x in dko.get(nm, []) if x and x != "-") or "-"
            pv = "/".join(x for x in dkp.get(nm, []) if x and x != "-") or "-"
            if ov != pv:
                skill_rows.append([p["name"], nm, "%s → **%s**" % (ov, pv)])

    L.append("## 7. 파일럿 정신 커맨드 교체")
    L.append("")
    L.append(md_table(["파일럿", "슬롯", "정신기", "SP", "습득 Lv"], sprt_rows))
    L.append("")
    L.append("## 8. 파일럿 SP 소모 / 습득 레벨")
    L.append("")
    L.append("`SP 변경 / 습득레벨 변경` 순서.")
    L.append("")
    L.append(md_table(["파일럿", "변경 내역"], sp_rows))
    L.append("")
    L.append("## 9. 파일럿 SP 총량")
    L.append("")
    L.append("게임 내 표시 SP 는 기본값에 레벨 성장분이 더해진 값이다. 예를 들어 라미아는")
    L.append("기본 60 이지만 시작 시점에 63 으로 보인다 (실기 확인).")
    L.append("")
    L.append("Lv10 / Lv30 열은 **원본 기준 참고값**이다. ODS 가 Plus 쪽 성장치를 적어두지")
    L.append("않았으므로, 기본값 상승분만큼 함께 올라간다고 보면 된다.")
    L.append("")
    L.append(md_table(["파일럿", "기본 SP", "원본 Lv10", "원본 Lv30"], base_sp_rows))
    L.append("")
    L.append("## 10. 파일럿 스킬 습득 레벨")
    L.append("")
    L.append("스킬 레벨 1→N 을 얻는 레벨. `-` 는 습득하지 않음.")
    L.append("")
    L.append(md_table(["파일럿", "스킬", "습득 레벨"], skill_rows))
    L.append("")
    L.append("## 11. 파일럿 지형 적응")
    L.append("")
    L.append(md_table(["파일럿", "공/육/수/우주"], pter_rows))
    L.append("")

    # ---------------- 부록
    L.append("## 부록. ODS 문서와 실제 패치가 어긋나는 항목")
    L.append("")
    L.append("변경목록은 2024-04, 패치 본체는 2024-08(v1.2) 이라 문서가 옛날 값을 담고 있다.")
    L.append("**패치 본체가 기준**이고, 본문 표의 ⚠️ 항목이 여기 해당한다.")
    L.append("")
    L.append(md_table(["유닛", "항목", "원본", "ODS 기재", "실제 패치"], drift))
    L.append("")
    L.append("### ODS 원본 열이 잘못 적힌 항목 (※)")
    L.append("")
    L.append("ODS 가 원본 수치로 적 버전의 스탯을 적어놓은 경우다. 변경 **후** 값은 ODS 대로")
    L.append("정확히 들어갔고, 잘못된 것은 문서의 원본 열이다.")
    L.append("")
    L.append(md_table(["유닛", "ODS 원본 (HP/EN/장갑/운동성)", "실제 원본", "실제 레코드"],
                      ods_err))
    L.append("")
    L.append("### 검증 범위")
    L.append("")
    L.append("- ODS 의 유닛 %d개 중 %d개는 원본 스탯이 다른 유닛과 겹쳐 ISO 대조에서 제외."
             % (len(robots), unver))
    L.append("- 대조한 %d개 중 %d개는 HP·EN·장갑·운동성 네 항목이 ODS Plus 값과 완전히 일치."
             % (len(robots) - unver, verified))
    L.append("- 나머지 %d개는 위 두 표에 정리했다." % (len(robots) - unver - verified))
    L.append("- 무기·파일럿 표는 ODS 값을 그대로 옮긴 것이다. 이 구간은 전수 대조가 아니라")
    L.append("  60mm 발칸(파워 1700 / 명중 50) 과 라미아(정신기 Strike/Guard/Assail,")
    L.append("  SP 15/20/15, 기본 SP 60) 표본 검증으로 매핑이 맞는 것만 확인했다.")
    L.append("")

    open(dest, "w").write("\n".join(L))
    print("%s 생성 — 유닛 %d / 파일럿 %d / 문서차이 %d건"
          % (dest, len(robots), len(pilots), len(drift)))
    print("   기본스탯 %d행, 개조 %d행, 무기 %d행, 정신기 %d행, 스킬 %d행"
          % (len(base_rows), len(upg_rows), len(wrows2), len(sprt_rows), len(skill_rows)))


if __name__ == "__main__":
    main()
