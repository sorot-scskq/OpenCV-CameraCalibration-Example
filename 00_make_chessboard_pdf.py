#!/usr/bin/env python3
"""
校正用のチェスボードを、A4 の実寸 PDF で作る（2026）。

    RoughSpot/Python/.venv/bin/python Tools/make_chessboard_pdf.py

**外部のライブラリを使わない。** PDF を直に書いている（中身は塗った四角だけ）。

既定は **A4 横・1マス 24.0mm・10x7 マス（内側の角 9x6）**。
盤は 240 x 168mm、まわりの余白は 28.5 x 21.0mm。
**余白は角の検出に要る**（`findChessboardCorners` は盤の外に明るい縁を求める）。

【印刷するとき】
* **「用紙に合わせる」「拡大縮小」を切って 100% で出す。** ここを外すと全部やり直し
* 出したら**下の物差しを定規で測る**。100.0mm でなければ、出た値を
  `calibrate_camera.py --square-mm` に入れる（刷り直さなくてよい）

      実際の1マス = 24.0 x (測った物差し / 100.0)

* **平らな板に貼る。** 紙の反りは、そのまま歪みの答えに化ける。
  クリップボードか、板に両面テープで四隅を留める
"""

import argparse
import os

MM = 72.0 / 25.4          # 1mm が何ポイントか

#: 用紙（横置き）。**A3 が刷れるならそちらが良い。** 盤が大きいほど遠くから角が取れ、
#: 画面の四隅を埋めやすい。歪みは縁で効くので、そこが埋まるかどうかが答えを決める
PAPERS = {"a4": (297.0, 210.0), "a3": (420.0, 297.0)}

#: 用紙ごとの既定の1マス[mm]。**10x7 マスが余白を残して収まる大きさ**
SQUARE_BY_PAPER = {"a4": 24.0, "a3": 34.0}

#: 1マスの長さ[mm]
SQUARE_MM = 24.0
#: マスの数（横, 縦）。**内側の角はこれから1ずつ引いた 9x6**
SQUARES = (10, 7)
#: 刷った倍率を確かめる物差しの長さ[mm]
RULER_MM = 100.0


class ChessboardPdf:
    """塗った四角だけの PDF を書く"""

    def __init__(self, square_mm=SQUARE_MM, squares=SQUARES,
                 page=PAPERS["a4"]):
        self.square_mm = float(square_mm)
        self.squares = squares
        self.page = page

    def board_mm(self):
        return self.squares[0] * self.square_mm, self.squares[1] * self.square_mm

    def margins_mm(self):
        bw, bh = self.board_mm()
        return (self.page[0] - bw) / 2.0, (self.page[1] - bh) / 2.0

    def _content(self) -> str:
        cols, rows = self.squares
        mx, my = self.margins_mm()
        s = self.square_mm
        # **白の下地を敷く。** 敷かないと背景が透明になり、画面で確かめるときに
        # 盤が真っ黒に潰れる（紙に刷れば白だが、digital で見ると気づけない）
        out = ["1 1 1 rg", "0 0 %.4f %.4f re f" % (self.page[0] * MM, self.page[1] * MM),
               "0 0 0 rg"]
        for r in range(rows):
            for c in range(cols):
                if (r + c) % 2:
                    continue
                # PDF の原点は左下。盤は上から並べたいので r を裏返す
                x = (mx + c * s) * MM
                y = (my + (rows - 1 - r) * s) * MM
                out.append("%.4f %.4f %.4f %.4f re f" % (x, y, s * MM, s * MM))

        # 倍率を確かめる物差し（下の余白に引く。**刷った紙を定規で測るため**）
        ry = (my / 2.0) * MM
        rx = mx * MM
        out.append("0.6 w")
        out.append("%.4f %.4f m %.4f %.4f l S" % (rx, ry, rx + RULER_MM * MM, ry))
        for i in range(int(RULER_MM // 10) + 1):
            x = rx + i * 10 * MM
            h = (3.5 if i % 5 else 6.0) * MM
            out.append("%.4f %.4f m %.4f %.4f l S" % (x, ry, x, ry + h))

        note = ("PRINT AT 100%% - NO SCALING  /  ruler = %.0fmm  /  square = %.1fmm  /  "
                "inner corners %dx%d" % (RULER_MM, self.square_mm, cols - 1, rows - 1))
        out.append("BT /F1 8 Tf %.4f %.4f Td (%s) Tj ET" % (
            rx + (RULER_MM + 6) * MM, ry - 1.0 * MM, note))
        return "\n".join(out)

    def write(self, path: str) -> str:
        content = self._content().encode("ascii", "replace")
        objs = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.4f %.4f] "
             "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
             % (self.page[0] * MM, self.page[1] * MM)).encode("ascii"),
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        body = b"%PDF-1.4\n"
        offsets = []
        for i, o in enumerate(objs, start=1):
            offsets.append(len(body))
            body += str(i).encode() + b" 0 obj\n" + o + b"\nendobj\n"
        start = len(body)
        body += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
        for off in offsets:
            body += ("%010d 00000 n \n" % off).encode()
        body += (b"trailer\n<< /Size " + str(len(objs) + 1).encode() +
                 b" /Root 1 0 R >>\nstartxref\n" + str(start).encode() + b"\n%%EOF\n")
        with open(path, "wb") as f:
            f.write(body)
        return path


def main() -> int:
    p = argparse.ArgumentParser(description="実寸のチェスボード PDF を作る")
    p.add_argument("--paper", default="a4", choices=sorted(PAPERS),
                   help="用紙（横置き）。**A3 が刷れるならそちらが良い**")
    p.add_argument("--square-mm", type=float, default=None,
                   help="1マス[mm]。省くと用紙に合わせる（A4 24.0 / A3 34.0）")
    p.add_argument("--out", default=None)
    a = p.parse_args()

    square = a.square_mm if a.square_mm else SQUARE_BY_PAPER[a.paper]
    out = a.out or ("chessboard_%s_%.0fmm.pdf" % (a.paper, square))
    board = ChessboardPdf(square_mm=square, page=PAPERS[a.paper])
    path = board.write(out)
    bw, bh = board.board_mm()
    mx, my = board.margins_mm()
    if min(mx, my) < square * 0.7:
        print("**余白が1マスの0.7倍より狭い。角の検出が落ちる。**"
              " --square-mm を小さくすること\n")
    print("書き出しました: %s" % os.path.abspath(path))
    print("  用紙        %s 横 %.1f x %.1f mm" % (
        a.paper.upper(), board.page[0], board.page[1]))
    print("  1マス       %.1f mm" % board.square_mm)
    print("  マス        %d x %d（**内側の角 %d x %d**）" % (
        board.squares[0], board.squares[1], board.squares[0] - 1, board.squares[1] - 1))
    print("  盤の大きさ  %.1f x %.1f mm" % (bw, bh))
    print("  余白        %.1f x %.1f mm" % (mx, my))
    print("\n**100% で印刷し、下の物差しを定規で測ること。**")
    print("100.0mm でなければ、実際の1マス = %.1f x (測った値 / 100.0)" % board.square_mm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
