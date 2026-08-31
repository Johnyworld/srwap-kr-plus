#!/usr/bin/env python3
"""
Super Robot Wars A Portable Plus (밸런스 패치) → 한글판 v2.4 ISO 이식기.

원본 APP 1_2.ppf 는 영문 Steel Soul 패치판 ISO 기준의 raw 오프셋 diff 라서
한글판에 그대로 적용하면 대사 데이터를 스탯 값으로 덮어쓴다.

이 스크립트는 패치가 건드리는 세 테이블을 한글판 ISO 안에서 찾아
오프셋을 재매핑한 뒤 적용한다. 매핑 근거는 README.md 참고.

  유닛 테이블   305개 × 0x68   영문 0x73534F0  → 한글 0x1C182CF0
  Weapxx 무기   1101개 × 0x1C  영문 0x735B0E4  → 한글 0x1C18A8E4
  PTbl 파일럿   0xC8 간격       영문 0x7362950  → 한글 0x1C192150

세 테이블 모두 동일한 델타 +0x14E2F800 로 정렬된다.
한글판 ISO 는 dummy.bin 안에 같은 데이터의 사본을 하나 더 갖고 있고
(게임이 파일명이 아니라 절대 LBA 로 읽기 때문에 어느 쪽이 로드되는지
불확실하다) 패치 범위에서 두 사본은 바이트 단위로 동일하므로 양쪽 다 쓴다.
"""

import argparse
import hashlib
import os
import shutil
import struct
import sys

# ---------------------------------------------------------------- 매핑 상수

ISO_SIZE = 1497790464

EN_UNIT_TABLE = 0x73534F0        # 영문판 유닛 테이블 시작 (= 패치 대형 클러스터 시작)
KR_UNIT_TABLE = 0x1C182CF0       # 한글판 shared.bin 안의 같은 테이블
DELTA = KR_UNIT_TABLE - EN_UNIT_TABLE            # 0x14E2F800

MIRROR = 0x14C46000              # dummy.bin 사본 = shared.bin 위치 - MIRROR

CLUSTER_START = 0x7353000        # 이 오프셋 이상인 PPF 레코드만 이식 대상

UNIT_COUNT = 305
UNIT_SIZE = 0x68
KR_WEAP_HDR = 0x1C18A8D8         # "Weapxx"
KR_WEAP_BASE = 0x1C18A8E4        # 무기 0번 레코드
WEAP_SIZE = 0x1C
KR_PTBL = 0x1C192150             # "PTbl"

# 이식 대상에서 제외하는 레코드와 그 이유
SKIP_REASONS = {
    0xC954: "ISO9660 디렉터리 레코드의 타임스탬프 (게임 데이터 아님)",
}
SKIP_RANGE = (0x6E5EAC8, 0x6E5EB29,
              "Aestivalis Lunar Frame 레코드의 잉여 사본 "
              "(메인 테이블 idx 231/285~289 이 같은 값으로 이미 갱신됨)")


# ---------------------------------------------------------------- PPF 파싱

def parse_ppf(path):
    p = open(path, "rb").read()
    if p[:5] != b"PPF30":
        raise SystemExit("PPF 3.0 파일이 아닙니다: %s" % path)
    blockcheck, undo = p[57], p[58]
    i = 60 + (1024 if blockcheck else 0)
    out = []
    while i < len(p):
        off = struct.unpack("<Q", p[i:i + 8])[0]
        i += 8
        n = p[i]
        i += 1
        data = p[i:i + n]
        i += n
        if undo:
            i += n
        out.append((off, data))
    return out


def classify(recs):
    """PPF 레코드를 (이식 대상, 건너뛴 것) 으로 나눈다."""
    port, skipped = [], []
    for off, data in recs:
        if off in SKIP_REASONS:
            skipped.append((off, data, SKIP_REASONS[off]))
        elif SKIP_RANGE[0] <= off <= SKIP_RANGE[1]:
            skipped.append((off, data, SKIP_RANGE[2]))
        elif off >= CLUSTER_START:
            port.append((off + DELTA, data))
        else:
            skipped.append((off, data, "매핑되지 않는 영역"))
    return port, skipped


# ---------------------------------------------------------------- 검증

def anchors_ok(f, verbose=True):
    """패치 전에 대상 ISO 가 예상한 한글판 v2.4 인지 확인한다."""
    checks = []

    def read(off, n):
        f.seek(off)
        return f.read(n)

    size = os.fstat(f.fileno()).st_size
    checks.append(("ISO 크기", size == ISO_SIZE, "%d" % size))
    checks.append(("유닛테이블 0x%X = RX-78(HP 3500/EN 80/장갑 1000)" % KR_UNIT_TABLE,
                   read(KR_UNIT_TABLE, 2) == b"\xac\x0d"
                   and read(KR_UNIT_TABLE + 0x1C, 2) == b"\x50\x00"
                   and read(KR_UNIT_TABLE + 0x1E, 2) == b"\xe8\x03",
                   read(KR_UNIT_TABLE, 8).hex()))
    checks.append(("무기테이블 헤더 0x%X = 'Weapxx'" % KR_WEAP_HDR,
                   read(KR_WEAP_HDR, 6) == b"Weapxx", read(KR_WEAP_HDR, 6).hex()))
    checks.append(("무기 1번 = 60mm 발칸(파워 1500)",
                   read(KR_WEAP_BASE + WEAP_SIZE + 6, 2) == b"\xdc\x05",
                   read(KR_WEAP_BASE + WEAP_SIZE, 12).hex()))
    checks.append(("파일럿테이블 헤더 0x%X = 'PTbl'" % KR_PTBL,
                   read(KR_PTBL, 4) == b"PTbl", read(KR_PTBL, 4).hex()))
    checks.append(("유닛테이블 끝 = 무기테이블 헤더",
                   KR_UNIT_TABLE + UNIT_COUNT * UNIT_SIZE == KR_WEAP_HDR, ""))

    # dummy.bin 사본이 패치 범위에서 shared.bin 과 동일한지
    lo, hi = KR_UNIT_TABLE, KR_PTBL + 0x6000
    a = read(lo, hi - lo)
    b = read(lo - MIRROR, hi - lo)
    checks.append(("dummy.bin 사본이 패치 범위(%d바이트)에서 동일" % (hi - lo),
                   a == b, "불일치 %d바이트" % sum(x != y for x, y in zip(a, b))))

    if verbose:
        for name, ok, detail in checks:
            print("   [%s] %s%s" % ("OK" if ok else "실패", name,
                                    ("  — " + detail) if (detail and not ok) else ""))
    return all(ok for _, ok, _ in checks)


SPOT_CHECKS = [
    # (설명, 오프셋, 기대 바이트)
    ("RX-78 HP 4000", KR_UNIT_TABLE + 0x00, b"\xa0\x0f"),
    ("RX-78 개조단계 7/8/8/6", KR_UNIT_TABLE + 0x08, b"\x87\x68"),
    ("RX-78 EN 95", KR_UNIT_TABLE + 0x1C, b"\x5f"),
    ("RX-78 장갑 1200", KR_UNIT_TABLE + 0x1E, b"\xb0\x04"),
    ("RX-78 운동성 95", KR_UNIT_TABLE + 0x5D, b"\x5f"),
    ("60mm 발칸 파워 1700 / 명중 +50",
     KR_WEAP_BASE + WEAP_SIZE + 6, b"\xa4\x06\x32"),
    ("라미아 정신기 Strike/Guard/Assail", 0x1C1970AC, b"\x09\x0c\x1d"),
    ("라미아 SP 소모 15/20/15", 0x1C1970B2, b"\x0f\x14\x0f"),
    ("라미아 기본 SP 60", 0x1C1970A4, b"\x3c"),
]


def spot_check(f):
    bad = []
    for name, off, want in SPOT_CHECKS:
        f.seek(off)
        got = f.read(len(want))
        if got != want:
            bad.append((name, off, want.hex(), got.hex()))
    return bad


# ---------------------------------------------------------------- PPF 생성

def write_ppf(path, writes, src):
    """한글판 전용 PPF 3.0 을 만든다. 원본 검증(blockcheck) 을 켠다."""
    runs = []
    for off, data in sorted(writes):
        if runs and off == runs[-1][0] + len(runs[-1][1]) and len(runs[-1][1]) + len(data) <= 255:
            runs[-1] = (runs[-1][0], runs[-1][1] + data)
        else:
            runs.append((off, bytes(data)))
    desc = b"SRW A Portable Plus 1.2 for Korean v2.4"
    with open(path, "wb") as o:
        o.write(b"PPF30" + bytes([2]))
        o.write(desc.ljust(50, b" ")[:50])
        o.write(bytes([0, 1, 0, 0]))          # imagetype, blockcheck=1, undo=0, dummy
        src.seek(0x9320)
        o.write(src.read(1024))
        for off, data in runs:
            o.write(struct.pack("<Q", off) + bytes([len(data)]) + data)
    return len(runs)


# ---------------------------------------------------------------- 메인

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iso", required=True, help="한글판 v2.4 ISO")
    ap.add_argument("--ppf", required=True, help="APP 1_2.ppf")
    ap.add_argument("--out", help="출력 ISO (생략하면 검사만)")
    ap.add_argument("--emit-ppf", help="한글판 전용 PPF 도 같이 생성")
    args = ap.parse_args()

    recs = parse_ppf(args.ppf)
    port, skipped = classify(recs)
    print("PPF 레코드 %d개 → 이식 %d개 / 건너뜀 %d개"
          % (len(recs), len(port), len(skipped)))
    for off, data, why in skipped:
        print("   건너뜀 0x%09X (%d바이트): %s" % (off, len(data), why))

    print("\n대상 ISO 검사:")
    with open(args.iso, "rb") as f:
        if not anchors_ok(f):
            raise SystemExit("\n대상 ISO 가 예상한 한글판 v2.4 가 아닙니다. 중단합니다.")

    # 양쪽 사본에 쓸 최종 목록
    writes = []
    for off, data in port:
        writes.append((off, data))
        writes.append((off - MIRROR, data))
    lo = min(o for o, _ in writes)
    hi = max(o + len(d) for o, d in writes)
    print("\n쓰기 대상: %d곳 / %d바이트 (shared.bin + dummy.bin 사본)"
          % (len(writes), sum(len(d) for _, d in writes)))
    print("   범위 0x%09X .. 0x%09X" % (lo, hi))

    if not args.out:
        print("\n--out 없음: 검사만 하고 종료합니다.")
        return

    print("\nISO 복사 중 ...")
    shutil.copyfile(args.iso, args.out)

    with open(args.out, "r+b") as f:
        for off, data in writes:
            f.seek(off)
            f.write(data)
        f.flush()
        os.fsync(f.fileno())

        print("적용 완료. 되읽어 검증합니다 ...")
        bad = 0
        for off, data in writes:
            f.seek(off)
            if f.read(len(data)) != data:
                bad += 1
        print("   되읽기 불일치: %d곳" % bad)

        problems = spot_check(f)
        print("   내용 검증 %d항목:" % len(SPOT_CHECKS))
        for name, off, want, got in problems:
            print("      [실패] %s @0x%X  기대=%s 실제=%s" % (name, off, want, got))
        if not problems:
            print("      전부 통과")
        if bad or problems:
            raise SystemExit("검증 실패 — 출력 ISO 를 사용하지 마십시오.")

        if args.emit_ppf:
            n = write_ppf(args.emit_ppf, writes, open(args.iso, "rb"))
            print("\n한글판 전용 PPF 생성: %s (%d 레코드, blockcheck 켜짐)"
                  % (args.emit_ppf, n))

    print("\n완료: %s" % args.out)


if __name__ == "__main__":
    main()
