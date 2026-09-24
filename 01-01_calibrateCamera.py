#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
チェスボードからカメラの内部パラメータと歪み係数を求める。

**動画を1本撮って、これに渡すだけで終わる。**

    python 01-01_calibrateCamera.py calib.mp4

画像の束でもフォルダでもよい。

    python 01-01_calibrateCamera.py 'chess/*.png'
    python 01-01_calibrateCamera.py chess/

何も渡さなければ、本家どおりカメラを開いて画面を見ながら撮る
（**画面のある機械でだけ動く**）。

盤は同梱の `chessboard_a4.pdf`（1マス 24.0mm・内側の角 9x6）を前提にしている。
**A3 を刷ったときと、刷った紙の物差しが 100.0mm でなかったときだけ** `--square_len`
を渡す（README の「盤の PDF を同梱した」を参照）。

本家からの変更点は README の「走行体で使うための変更」にまとめてある。
"""
import argparse
import glob
import json
import math
import os
import sys

import cv2 as cv
import numpy as np

#: 盤（同梱の chessboard_a4.pdf）。**内側の角**の数で、マスの数ではない
GRID_SIZE = (9, 6)
#: 同上、1マスの長さ[mm]
SQUARE_LEN = 24.0

#: 埋まりを数えるときの画面の分割
COVER_COLS = 4
COVER_ROWS = 3

#: 動画を何枚おきに見るか。30fps なら 5 で毎秒6枚。**全部見ても精度は上がらない**
VIDEO_STEP = 5
#: 動画から採る上限。**似た絵を増やしても精度は上がらず、遅くなるだけ**
VIDEO_MAX_FRAMES = 40
#: 直前に採った枚から、角が平均で何px動いたら別の姿勢とみなすか
VIDEO_MIN_MOVE_PX = 40.0
#: ラプラシアンの分散の下限。**動画は必ずブレるので、ここで捨てる**
MIN_SHARPNESS = 40.0

#: 動画・画像として扱う拡張子
VIDEO_EXT = ('.mp4', '.mov', '.avi', '.mkv', '.m4v', '.mts')
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')

#: 走行するときの絵の大きさ。**ここと違う大きさで校正したら警告する**
#:
#: 歪みの係数（k1 k2 p1 p2 k3）は正規化座標に掛かるので、それ自体は解像度に依らない。
#: `fx fy cx cy` は画素なので比例し、倍率を掛ければ移せる——**縮小しているだけなら。**
#:
#: **多くの USB カメラは、解像度を変えると切り出し方まで変える。** そうなると画角が
#: 別物になり、どう倍率を掛けても移せない。縮小か切り出しかは外から分からないので、
#: **走行と同じ大きさで撮る**のが唯一の安全な規則。
#:
#: **それだけではない。縮小しているだけでも、係数の当てはめが荒くなる。**
#: 同じ合成写真を 1280x720 と、それを単純に縮小した 640x360 で解いた実測:
#:
#:     1280x720   fx 1249.7  hfov 54.24°  k1 -0.3587  k2 +0.1799  k3 -0.1668
#:      640x360   fx  624.0  hfov 54.30°  k1 -0.3228  k2 -0.2614  k3 +1.4088
#:
#: `fx` はきれいに半分になり画角も合うが、**`k1` は 10% ずれ、`k2`/`k3` は符号ごと
#: 変わっている**（角の位置の精度が落ち、高次の項が互いに融通し合うため）。
#: **切り出しが無い理想の場合ですらこれだけ動く。**
RUN_SIZE = (1280, 720)


def get_args():
    parser = argparse.ArgumentParser(
        description='チェスボードからカメラの歪みを求める（動画1本でよい）')
    parser.add_argument(
        'input', nargs='?', default=None,
        help='動画 / 画像のフォルダ / 画像のパターン。省くとカメラを開く')
    parser.add_argument(
        '--square_len', type=float, default=SQUARE_LEN,
        help='1マスの長さ[mm]。**刷った紙の物差しを定規で測った値**（既定 %.1f）'
             % SQUARE_LEN)
    return parser.parse_args()


class Coverage:
    """画面のどこを撮れたかを数える

    **これが無いと、写真が画面の一部に偏っていても気づけない。**
    歪みは縁で効くので、中央ばかりの束では四隅が当てはめの外挿になり、
    答えが出たように見えて実は決まっていない。
    """

    def __init__(self, width, height, points_per_image):
        self.width = width
        self.height = height
        self.points_per_image = points_per_image
        self.cells = [[0] * COVER_COLS for _ in range(COVER_ROWS)]

    def add(self, corners):
        for (x, y) in np.asarray(corners).reshape(-1, 2):
            c = min(COVER_COLS - 1, max(0, int(x * COVER_COLS / self.width)))
            r = min(COVER_ROWS - 1, max(0, int(y * COVER_ROWS / self.height)))
            self.cells[r][c] += 1

    def thin(self, need=2):
        """まだ薄いマスの数。**点の数ではなく、おおよその枚数で数える**"""
        floor = need * self.points_per_image // 8
        return sum(1 for row in self.cells for v in row if v < floor)

    def gain(self, corners, need=2):
        """この枚を採ると、薄いマスがいくつ埋まるか"""
        before = self.thin(need)
        saved = [row[:] for row in self.cells]
        self.add(corners)
        after = self.thin(need)
        self.cells = saved
        return before - after

    def show(self):
        print('画面の埋まり（左上から。数は角の点の数）:')
        for row in self.cells:
            print('   ' + ' '.join('%4d' % v for v in row))
        thin = self.thin()
        if thin:
            print('**まだ %d マスが薄い。そこを狙ってもう一度撮ると、答えが締まる。**'
                  % thin)
        else:
            print('全マス足りている。')


def open_camera():
    """開けたカメラを返す。**番号は指定しない**（機械によって違うので順に試す）"""
    for device in range(4):
        # **CAP_DSHOW は Windows 専用。** Linux（走行体）で渡すと開けない
        if sys.platform.startswith('win'):
            cap = cv.VideoCapture(device, cv.CAP_DSHOW)
        else:
            cap = cv.VideoCapture(device)
        if cap.isOpened():
            cap.set(cv.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv.CAP_PROP_FRAME_HEIGHT, 720)
            return cap
        cap.release()
    raise SystemExit(
        'カメラを開けません。\n'
        '  ・別のプログラムが掴んでいないか（走行体なら `sudo pkill -f ev3_python`）\n'
        '  ・`ls /dev/video*` でカメラが見えるか')


def refine(gray, corner):
    """角を画素より細かく詰める。**ここを飛ばすと残差が倍になる**"""
    criteria = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    return cv.cornerSubPix(gray, corner, (11, 11), (-1, -1), criteria)


def sharpness(gray):
    return cv.Laplacian(gray, cv.CV_64F).var()


def edge_shift(K, d, width, height):
    """**縁が何画素動くか。** これが小さいなら、歪みはその症状の原因ではない"""
    probes = np.array([[[0.0, 0.0]], [[width - 1.0, 0.0]], [[0.0, height - 1.0]],
                       [[width - 1.0, height - 1.0]],
                       [[width / 2.0, 0.0]], [[width / 2.0, height - 1.0]]])
    fixed = cv.undistortPoints(probes, K, d, P=K)
    return [float(np.hypot(*(fixed[i][0] - probes[i][0])))
            for i in range(len(probes))]


class Collector:
    """盤の角を集める。動画でも画像でもカメラでも、集め方だけが違う"""

    def __init__(self, square_len):
        self.pattern_points = np.zeros((np.prod(GRID_SIZE), 3), np.float32)
        self.pattern_points[:, :2] = np.indices(GRID_SIZE).T.reshape(-1, 2)
        self.pattern_points *= square_len
        self.object_points = []
        self.image_points = []
        self.names = []
        self.size = None
        self.coverage = None

    def _keep(self, corner, name):
        self.image_points.append(corner)
        self.object_points.append(self.pattern_points)
        self.coverage.add(corner)
        self.names.append(name)

    def _prepare(self, gray):
        if self.size is None:
            self.size = (gray.shape[1], gray.shape[0])
            self.coverage = Coverage(self.size[0], self.size[1],
                                     int(np.prod(GRID_SIZE)))
            return True
        return (gray.shape[1], gray.shape[0]) == self.size

    def from_video(self, path):
        """**動画1本から、姿勢の違う枚だけを選って採る。**

        全部の枚を採ってはいけない。30fps なら隣り合う枚はほぼ同じで、
        **精度は上がらないのに時間だけ増え、よく写った区間に重みが偏る。**
        """
        cap = cv.VideoCapture(path)
        if not cap.isOpened():
            raise SystemExit('動画を開けません: %s' % path)
        total = int(cap.get(cv.CAP_PROP_FRAME_COUNT) or 0)
        print('動画 %s（%d枚 / %.1ffps）' % (
            os.path.basename(path), total, cap.get(cv.CAP_PROP_FPS) or 0))

        index, looked, blurred, found_count, last = -1, 0, 0, 0, None
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            index += 1
            if index % VIDEO_STEP:
                continue
            looked += 1
            gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
            if not self._prepare(gray):
                continue
            if sharpness(gray) < MIN_SHARPNESS:
                blurred += 1
                continue
            ok, corner = cv.findChessboardCorners(gray, GRID_SIZE)
            if not ok:
                continue
            found_count += 1
            corner = refine(gray, corner)

            flat = np.asarray(corner).reshape(-1, 2)
            moved = VIDEO_MIN_MOVE_PX if last is None else float(
                np.linalg.norm(flat - last, axis=1).mean())
            # **姿勢が変わったか、薄いマスが埋まるときだけ採る**
            if moved < VIDEO_MIN_MOVE_PX and self.coverage.gain(corner) <= 0:
                continue
            if len(self.object_points) >= VIDEO_MAX_FRAMES:
                continue
            last = flat
            self._keep(corner, '%.1fs' % (index / (cap.get(cv.CAP_PROP_FPS) or 30.0)))
        cap.release()

        print('  見た %d枚 / 盤が写っていた %d枚 / ブレて捨てた %d枚 / **採った %d枚**'
              % (looked, found_count, blurred, len(self.object_points)))
        return self

    def from_images(self, paths):
        print('画像 %d 枚' % len(paths))
        for path in paths:
            frame = cv.imread(path)
            if frame is None:
                continue
            gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
            if not self._prepare(gray):
                print('  %s は大きさが違う（捨てた）' % os.path.basename(path))
                continue
            ok, corner = cv.findChessboardCorners(gray, GRID_SIZE)
            if not ok:
                print('  %s に盤が無い' % os.path.basename(path))
                continue
            self._keep(refine(gray, corner), os.path.basename(path))
        return self

    def from_camera(self):
        """**カメラを映したまま、勝手に集めて勝手に終わる。**

        キーを押す必要は無い。盤の姿勢が変わるか、薄いマスが埋まるときだけ採り、
        **画面の全マスが埋まったら自分で止まって解きにいく。**

        画面が無い機械（SSH 越しの走行体）でも動く。窓が開けなければ、
        文字だけで同じことを言う。
        """
        cap = open_camera()
        window = True
        print('カメラを開きました。**盤をカメラに見せてください。**')
        print('  ・画面の四隅まで運ぶ（歪みは縁で効く）')
        print('  ・寝かせ・起こし・ひねる（±30〜45°）')
        print('  ・ゆっくり動かす')
        print('**全部埋まれば自分で止まります。** 途中でやめるときは Ctrl-C。\n')

        last, shown = None, -1
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
                self._prepare(gray)

                ok, corner = cv.findChessboardCorners(gray, GRID_SIZE)
                if ok and sharpness(gray) >= MIN_SHARPNESS:
                    corner = refine(gray, corner)
                    flat = np.asarray(corner).reshape(-1, 2)
                    moved = VIDEO_MIN_MOVE_PX if last is None else float(
                        np.linalg.norm(flat - last, axis=1).mean())
                    if moved >= VIDEO_MIN_MOVE_PX or self.coverage.gain(corner) > 0:
                        last = flat
                        self._keep(corner, 'shot%03d' % (len(self.object_points) + 1))
                elif ok:
                    corner = None  # ブレている。写ってはいるので枠だけ描く

                thin = self.coverage.thin() if self.coverage else COVER_COLS * COVER_ROWS
                if len(self.object_points) != shown:
                    shown = len(self.object_points)
                    print('  採った %2d枚  **薄いマス %d**' % (shown, thin))

                if window:
                    window = self._draw(frame, ok, corner, thin)

                # **全部埋まったら自分で止まる。** 枚数だけでは偏った束で止まりうる
                if thin == 0 and len(self.object_points) >= 12:
                    print('\n全マス埋まりました。解きにいきます。')
                    break
                # **埋まらないまま溜め続けない。** 40枚あれば足り、それ以上は
                # 解くのが遅くなるだけ。埋まっていないなら撮り方のほうを直す
                if len(self.object_points) >= VIDEO_MAX_FRAMES:
                    print('\n%d枚まで集めました（**薄いマスが %d 残っています**）。'
                          '解きにいきます。' % (VIDEO_MAX_FRAMES, thin))
                    break
                if cv.waitKey(1) & 0xFF == 27:  # ESC
                    break
        except KeyboardInterrupt:
            print('\n止めました。集まったぶんで解きます。')
        finally:
            cap.release()
            if window:
                try:
                    cv.destroyAllWindows()
                except cv.error:
                    pass
        return self

    def _draw(self, frame, ok, corner, thin):
        """窓に映す。**開けなければ二度と試さない**（画面の無い機械で毎周期失敗しない）"""
        if ok and corner is not None:
            cv.drawChessboardCorners(frame, GRID_SIZE, corner, ok)
        cv.putText(frame, "kept:%d  thin:%d  (ESC to stop)" % (
            len(self.object_points), thin),
            (10, 30), cv.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        if self.coverage is not None:
            self._draw_coverage(frame)
        try:
            cv.imshow('calibration', frame)
            return True
        except cv.error:
            print('（画面が無いので、文字だけで進めます）')
            return False

    def _draw_coverage(self, frame):
        """**どこがまだ薄いかを画面に重ねる。** 見ながら盤を運べる"""
        h, w = frame.shape[:2]
        floor = 2 * int(np.prod(GRID_SIZE)) // 8
        for r in range(COVER_ROWS):
            for c in range(COVER_COLS):
                if self.coverage.cells[r][c] >= floor:
                    continue
                x0, y0 = int(c * w / COVER_COLS), int(r * h / COVER_ROWS)
                x1, y1 = int((c + 1) * w / COVER_COLS), int((r + 1) * h / COVER_ROWS)
                cv.rectangle(frame, (x0 + 2, y0 + 2), (x1 - 2, y1 - 2),
                             (0, 0, 255), 2)


def resolve_input(text):
    """渡されたものが動画か、画像の束かを判断する"""
    path = os.path.expanduser(text)
    if os.path.isdir(path):
        paths = sorted(p for p in glob.glob(os.path.join(path, '*'))
                       if p.lower().endswith(IMAGE_EXT))
        if not paths:
            raise SystemExit('フォルダに画像がありません: %s' % path)
        return 'images', paths
    if path.lower().endswith(VIDEO_EXT):
        if not os.path.exists(path):
            raise SystemExit('動画が見つかりません: %s' % path)
        return 'video', path
    paths = sorted(glob.glob(path))
    if not paths:
        raise SystemExit('見つかりません: %s' % text)
    return 'images', paths


def main():
    args = get_args()
    collector = Collector(args.square_len)

    if args.input is None:
        collector.from_camera()
    else:
        kind, value = resolve_input(args.input)
        if kind == 'video':
            collector.from_video(value)
        else:
            collector.from_images(value)

    if len(collector.image_points) < 5:
        raise SystemExit(
            '\n盤が取れたのが %d 枚しかありません。**もう一度撮ってください。**\n'
            '  ・盤を画面の四隅まで運ぶ（歪みは縁で効く）\n'
            '  ・寝かせ・起こし・ひねる（正対ばかりだと焦点距離が決まらない）\n'
            '  ・ゆっくり動かす（動画はブレやすい）'
            % len(collector.image_points))

    print('\ncalibrateCamera()')
    rms, K, d, r, t = cv.calibrateCamera(
        collector.object_points, collector.image_points, collector.size,
        None, None)

    # 1枚ごとの再投影誤差。**悪い1枚が全体を引っぱっていないかを見る**
    # **引く前に (N, 2) へそろえること。** projectPoints() は (N, 1, 2)、
    # findChessboardCorners() は版によって (N, 2) を返す。そろえずに引くと
    # (N, N, 2) へ広がり、もっともらしく大きい数字が出る
    per_image = []
    for i in range(len(collector.object_points)):
        projected, _ = cv.projectPoints(collector.object_points[i], r[i], t[i],
                                        K, d)
        diff = (projected.reshape(-1, 2)
                - np.asarray(collector.image_points[i]).reshape(-1, 2))
        per_image.append(float(np.sqrt((diff ** 2).sum() / len(diff))))

    width, height = collector.size
    if (width, height) != RUN_SIZE:
        print('\n**注意: %dx%d で校正しました。走行は %dx%d です。**' % (
            width, height, RUN_SIZE[0], RUN_SIZE[1]))
        print('  歪みの係数は解像度に依りませんが、**fx fy cx cy は画素なので'
              '倍率を掛けないと使えません**（x%.3f / y%.3f）。' % (
                  RUN_SIZE[0] / width, RUN_SIZE[1] / height))
        print('  **さらに、カメラが解像度で切り出し方を変えていると、倍率では'
              '移せません**（画角が別物になる）。')
        print('  **走行と同じ %dx%d で撮り直すのが確実です。**' % RUN_SIZE)

    shifts = edge_shift(K, d, width, height)
    hfov = math.degrees(2 * math.atan(width / 2 / K[0][0]))
    vfov = math.degrees(2 * math.atan(height / 2 / K[1][1]))

    np.savetxt('K.csv', K, delimiter=',', fmt="%0.14f")
    np.savetxt('d.csv', d, delimiter=',', fmt="%0.14f")
    with open('calibration.json', 'w') as f:
        json.dump({
            'width': width, 'height': height,
            'camera_matrix': K.tolist(), 'dist_coeffs': d.ravel().tolist(),
            'rms_px': float(rms), 'images': len(collector.object_points),
            'square_len': args.square_len, 'grid_size': list(GRID_SIZE),
            'hfov_deg': round(hfov, 2), 'vfov_deg': round(vfov, 2),
            'edge_shift_px': [round(s, 1) for s in shifts],
        }, f, ensure_ascii=False, indent=2)

    print('\n使えた枚数        %d' % len(collector.object_points))
    print('残差 rms          %.3f px   %s' % (
        rms, '良い' if rms < 0.5 else '**大きい。盤の反り・ブレ・枚数を疑う**'))
    print('焦点距離 fx / fy  %.1f / %.1f px' % (K[0][0], K[1][1]))
    print('画像の中心 cx/cy  %.1f / %.1f px（画面の中心は %.1f / %.1f）' % (
        K[0][2], K[1][2], width / 2, height / 2))
    print('画角              hfov %.2f°  vfov %.2f°' % (hfov, vfov))
    print('歪み k1 k2 p1 p2 k3  %s' % ' '.join(
        '%+.4f' % v for v in d.ravel()[:5]))
    print('\n**縁が動く量**    四隅 %s px / 上下の中央 %s px' % (
        [round(s, 1) for s in shifts[:4]], [round(s, 1) for s in shifts[4:]]))
    worst = sorted(zip(per_image, collector.names), reverse=True)[:3]
    print('残差の悪い3枚     %s' % ', '.join(
        '%s %.2fpx' % (n, v) for v, n in worst))
    if collector.coverage is not None:
        print('')
        collector.coverage.show()
    print('\n書き出しました: K.csv / d.csv / calibration.json')


if __name__ == '__main__':
    main()
