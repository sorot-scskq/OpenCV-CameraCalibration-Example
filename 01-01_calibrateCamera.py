#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
チェスボードからカメラの内部パラメータと歪み係数を求める。

本家（Kazuhito00/OpenCV-CameraCalibration-Example）からの変更点は README の
「走行体で使うための変更」を参照。要点だけ:

* `--images` を足した。**画面の無い機械（SSH 越しの走行体）で使えるようにするため**
* `cornerSubPix()` を足した。**角を画素より細かく詰めないと残差が倍になる**
* **画面のどこがまだ埋まっていないか**を出す。歪みは縁で効くので、
  真ん中ばかり撮っても決まらない
* **縁が何画素動くか**を出す。「歪みを取る価値があるか」の答えはこれ
* 1枚ごとの再投影誤差を出す。**悪い1枚が全体を引っぱっていないか**を見る
* `eval()` をやめ、`CAP_DSHOW` を Windows のときだけにした
"""
import argparse
import glob
import json
import math
import os
import sys

import cv2 as cv
import numpy as np

#: 埋まりを数えるときの画面の分割
COVER_COLS = 4
COVER_ROWS = 3


def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--file", type=str, default=None)
    parser.add_argument(
        "--images",
        type=str,
        default=None,
        help="画像から求める（例 'chess/*.png'）。**画面もカメラも要らない**")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)

    parser.add_argument("--square_len", type=float, default=23.0)
    parser.add_argument(
        "--grid_size",
        type=str,
        default="10,7",
        help="**内側の角**の数。マスの数ではない（10x7 マスの盤は 9,6）")

    parser.add_argument("--k_filename", type=str, default="K.csv")
    parser.add_argument("--d_filename", type=str, default="d.csv")
    parser.add_argument("--json_filename", type=str, default="calibration.json")

    parser.add_argument("--interval_time", type=int, default=500)
    parser.add_argument('--use_autoappend', action='store_true')

    args = parser.parse_args()

    return args


def parse_grid_size(text):
    """`"10,7"` を `(10, 7)` にする。**`eval()` は使わない**"""
    try:
        values = tuple(int(v) for v in text.replace('x', ',').split(','))
    except ValueError:
        values = ()
    if len(values) != 2:
        raise SystemExit('--grid_size は "10,7" の形で渡してください（内側の角の数）')
    return values


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

    def show(self):
        print('画面の埋まり（左上から。数は角の点の数）:')
        for row in self.cells:
            print('   ' + ' '.join('%4d' % v for v in row))
        thin = self.thin()
        if thin:
            print('**まだ %d マスが薄い。そこへ盤を運んで撮り足すこと。**' % thin)
        else:
            print('全マス足りている。')


def refine(gray, corner):
    """角を画素より細かく詰める。**ここを飛ばすと残差が倍になる**"""
    criteria = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    return cv.cornerSubPix(gray, corner, (11, 11), (-1, -1), criteria)


def edge_shift(K, d, width, height):
    """**縁が何画素動くか。** これが小さいなら、歪みはその症状の原因ではない"""
    probes = np.array([[[0.0, 0.0]], [[width - 1.0, 0.0]], [[0.0, height - 1.0]],
                       [[width - 1.0, height - 1.0]],
                       [[width / 2.0, 0.0]], [[width / 2.0, height - 1.0]]])
    fixed = cv.undistortPoints(probes, K, d, P=K)
    return [float(np.hypot(*(fixed[i][0] - probes[i][0]))) for i in range(len(probes))]


def collect_from_images(pattern, grid_intersection_size, pattern_points):
    """画像の束から角を拾う。**画面もカメラも要らない**"""
    paths = sorted(glob.glob(os.path.expanduser(pattern)))
    if not paths:
        raise SystemExit('画像が見つかりません: %s' % pattern)
    print('画像 %d 枚' % len(paths))

    object_points, image_points, used, size, coverage = [], [], [], None, None
    for path in paths:
        frame = cv.imread(path)
        if frame is None:
            continue
        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        if size is None:
            size = (gray.shape[1], gray.shape[0])
            coverage = Coverage(size[0], size[1], np.prod(grid_intersection_size))
        elif (gray.shape[1], gray.shape[0]) != size:
            print('  %s は大きさが違う（捨てた）' % os.path.basename(path))
            continue
        found, corner = cv.findChessboardCorners(gray, grid_intersection_size)
        if not found:
            print('  %s に盤が無い' % os.path.basename(path))
            continue
        corner = refine(gray, corner)
        image_points.append(corner)
        object_points.append(pattern_points)
        coverage.add(corner)
        used.append(os.path.basename(path))
    return object_points, image_points, used, size, coverage


def collect_from_camera(args, grid_intersection_size, pattern_points):
    """本家どおり、画面を見ながら撮って拾う。**画面のある機械でだけ使える**"""
    if args.file is None:
        # **CAP_DSHOW は Windows 専用。** Linux（走行体）で渡すと開けない
        if sys.platform.startswith('win'):
            cap = cv.VideoCapture(args.device, cv.CAP_DSHOW)
        else:
            cap = cv.VideoCapture(args.device)
        cap.set(cv.CAP_PROP_FRAME_WIDTH, args.width)
        cap.set(cv.CAP_PROP_FRAME_HEIGHT, args.height)
    else:
        cap = cv.VideoCapture(args.file)

    interval_time = args.interval_time if args.use_autoappend else 10
    object_points, image_points, size, coverage = [], [], None, None
    capture_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        if size is None:
            size = (gray.shape[1], gray.shape[0])
            coverage = Coverage(size[0], size[1], np.prod(grid_intersection_size))

        found, corner = cv.findChessboardCorners(gray, grid_intersection_size)
        if found:
            corner = refine(gray, corner)
            print('findChessboardCorners() : True')
            cv.drawChessboardCorners(frame, grid_intersection_size, corner, found)
        else:
            print('findChessboardCorners() : False')

        cv.putText(frame, "Enter:Capture Chessboard(" + str(capture_count) + ")",
                   (10, 30), cv.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
        cv.putText(frame, "ESC :Completes Calibration Photographing", (10, 55),
                   cv.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
        if coverage is not None:
            cv.putText(frame, "thin cells: " + str(coverage.thin()), (10, 80),
                       cv.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
        cv.imshow('original', frame)

        key = cv.waitKey(interval_time) & 0xFF
        if ((args.use_autoappend and found)
                or (not args.use_autoappend and key == 13 and found)):
            image_points.append(corner)
            object_points.append(pattern_points)
            coverage.add(corner)
            capture_count += 1
        if key == 27:  # ESC
            break

    cap.release()
    cv.destroyAllWindows()
    names = ['frame%03d' % (i + 1) for i in range(len(object_points))]
    return object_points, image_points, names, size, coverage


def main():
    args = get_args()
    grid_intersection_size = parse_grid_size(args.grid_size)

    # チェスボードの格子の、実寸での位置
    pattern_points = np.zeros((np.prod(grid_intersection_size), 3), np.float32)
    pattern_points[:, :2] = np.indices(grid_intersection_size).T.reshape(-1, 2)
    pattern_points *= args.square_len

    if args.images:
        object_points, image_points, names, size, coverage = collect_from_images(
            args.images, grid_intersection_size, pattern_points)
    else:
        object_points, image_points, names, size, coverage = collect_from_camera(
            args, grid_intersection_size, pattern_points)

    if len(image_points) < 5:
        raise SystemExit('盤が取れたのが %d 枚しかありません。'
                         '**10枚以上、四隅と傾きを入れて撮り直してください**'
                         % len(image_points))

    print('\ncalibrateCamera()')
    rms, K, d, r, t = cv.calibrateCamera(object_points, image_points, size,
                                         None, None)

    # 1枚ごとの再投影誤差。**悪い1枚が全体を引っぱっていないかを見る**
    # **引く前に (N, 2) へそろえること。** projectPoints() は (N, 1, 2)、
    # findChessboardCorners() は版によって (N, 2) を返す。そろえずに引くと
    # (N, N, 2) へ広がり、もっともらしく大きい数字が出る
    per_image = []
    for i in range(len(object_points)):
        projected, _ = cv.projectPoints(object_points[i], r[i], t[i], K, d)
        diff = projected.reshape(-1, 2) - np.asarray(image_points[i]).reshape(-1, 2)
        per_image.append(float(np.sqrt((diff ** 2).sum() / len(diff))))

    shifts = edge_shift(K, d, size[0], size[1])
    hfov = math.degrees(2 * math.atan(size[0] / 2 / K[0][0]))
    vfov = math.degrees(2 * math.atan(size[1] / 2 / K[1][1]))

    np.savetxt(args.k_filename, K, delimiter=',', fmt="%0.14f")
    np.savetxt(args.d_filename, d, delimiter=',', fmt="%0.14f")
    with open(args.json_filename, 'w') as f:
        json.dump({
            'width': size[0], 'height': size[1],
            'camera_matrix': K.tolist(), 'dist_coeffs': d.ravel().tolist(),
            'rms_px': float(rms), 'images': len(object_points),
            'square_len': args.square_len,
            'grid_size': list(grid_intersection_size),
            'hfov_deg': round(hfov, 2), 'vfov_deg': round(vfov, 2),
            'edge_shift_px': [round(s, 1) for s in shifts],
        }, f, ensure_ascii=False, indent=2)

    print('\n使えた写真        %d 枚' % len(object_points))
    print('残差 rms          %.3f px   %s' % (
        rms, '良い' if rms < 0.5 else '**大きい。盤の反り・ぼけ・枚数を疑う**'))
    print('焦点距離 fx / fy  %.1f / %.1f px' % (K[0][0], K[1][1]))
    print('画像の中心 cx/cy  %.1f / %.1f px（画面の中心は %.1f / %.1f）' % (
        K[0][2], K[1][2], size[0] / 2, size[1] / 2))
    print('画角              hfov %.2f°  vfov %.2f°' % (hfov, vfov))
    print('歪み k1 k2 p1 p2 k3  %s' % ' '.join(
        '%+.4f' % v for v in d.ravel()[:5]))
    print('\n**縁が動く量**    四隅 %s px / 上下の中央 %s px' % (
        [round(s, 1) for s in shifts[:4]], [round(s, 1) for s in shifts[4:]]))
    worst = sorted(zip(per_image, names), reverse=True)[:3]
    print('残差の悪い3枚     %s' % ', '.join('%s %.2fpx' % (n, v) for v, n in worst))
    if coverage is not None:
        print('')
        coverage.show()
    print('\n書き出しました: %s / %s / %s' % (
        args.k_filename, args.d_filename, args.json_filename))


if __name__ == '__main__':
    main()
