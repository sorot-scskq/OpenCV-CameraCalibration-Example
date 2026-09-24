# OpenCV-CameraCalibration-Example
https://user-images.githubusercontent.com/37477845/122794701-8086b900-d2f7-11eb-8651-ce4e300e8a83.mp4

OpenCVを用いたカメラキャリブレーションのサンプルです<br>
2021/06/21時点でPython実装のある以下3種類について用意しています。
* 通常カメラ向け
* 魚眼レンズ向け(fisheyeモジュール)
* 全方位カメラ向け(omnidirモジュール)<br>
全方位カメラは以下のような構造のカメラを想定しています。<br>
<img src="https://user-images.githubusercontent.com/37477845/122723516-067e1200-d2ae-11eb-8ce4-6ca891111160.png" width="50%"><br>
画像はWikipediaの[Omnidirectional (360-degree) camera](https://en.wikipedia.org/wiki/Omnidirectional_(360-degree)_camera)から引用<br>


---

# 走行体で使うための変更（sorot-scskq のフォーク）

**ETロボコンの走行体（SPIKE + RasPike-ART）のカメラを校正するために直した点。**
本家との差はここにまとめてある。上流へ戻す意図は無い。

## なぜ校正するのか

`grid_heading.py` には「レンズの歪みは先に `cv2.undistort` で取っておくこと」と
書いてあるのに、呼び出しが1つも無い。そのため目印の格子で向きを測る道は
**2026-09-21 の実機で 432回中2回、2026-09-23 でも 80回中5回**しか成立していない。
位置の打ち直しはこの測りを前提にしているので、**一度も動いていない。**

歪んだ絵を平面として引き直すと、中央と周辺で縮尺が違う。**格子が格子でなくなる。**
どんな（俯角・画角）を入れても全部の目印が同時に正しい位置へは来ない。

## 直した点

| | なぜ |
| --- | --- |
| **カメラを映したまま自動で集めて自動で終わるようにした** | 本家は Enter を押して1枚ずつ溜める。**盤を動かしながら片手でキーは押せない。** 姿勢が変わったときだけ勝手に採り、全マス埋まったら止まる |
| **動画1本でも通るようにした** | **走行体は SSH 越しで画面が無い。** 本家は `cv.imshow` / `waitKey` が要り、一度も動かせない。動画・画像・フォルダを位置引数で受け、姿勢の違う枚だけ選って採る |
| **オプションを消した** | 渡すのは `--square_len` だけ。盤は同梱の PDF に合わせて既定にした |
| **`cornerSubPix()` を足した** | 角を画素より細かく詰めないと**残差が倍**になる |
| **画面の埋まりを出す** | **歪みは縁で効く。** 俯角21°で床を見ていると写真が下半分に偏り、四隅が当てはめの外挿になる。答えが出たように見えて決まっていない |
| **縁が何画素動くかを出す** | **「歪みを取る価値があるか」の答えがこれ。** 係数そのものではない |
| **1枚ごとの再投影誤差を出す** | 悪い1枚が全体を引っぱっていないかを見る |
| `eval()` をやめた | `--grid_size` を素直に解く |
| `CAP_DSHOW` を Windows だけに | **Linux（走行体）では開けない** |
| 既定を 1280x720 に | 走行と同じ大きさで撮る |
| `calibration.json` も書く | CSV 2本だと画角や縁の移動量を残せない |

**`projectPoints()` は `(N, 1, 2)`、`findChessboardCorners()` は `(N, 2)` を返す。**
そろえずに引くと `(N, N, 2)` へ広がり、**もっともらしく大きい数字**が出る
（机上で 1732px を見た）。本家もここは `reshape(-1, 2)` で揃えてある。

## 盤の PDF を同梱した

**同梱の `chesspattern_7x10.pdf` は A4 縦**（210 x 297mm）。1マスの実寸は書かれておらず、
`--square_len` の既定が 23.0 という半端な値なのはそのため。

そこで**実寸を指定して作れる PDF と、その生成器**を足した。

| ファイル | 用紙 | 1マス | 盤 | 内側の角 |
| --- | --- | --- | --- | --- |
| `chessboard_a4.pdf` | A4 横 | 24.0mm | 240 x 168mm | **9x6** |
| `chessboard_a3.pdf` | A3 横 | 34.0mm | 340 x 238mm | **9x6** |

```bash
python 00_make_chessboard_pdf.py --paper a3          # 作り直すとき
```

**どちらにも 100mm の物差しを一緒に刷ってある。** 刷った紙を定規で測り、
100.0mm でなければ刷り直さずに実測値を使う。

```
実際の1マス = 24.0 x (測った物差し / 100.0)
```

**A3 が刷れるならそちらが良い。** 盤が大きいほど遠くからでも角が取れ、
画面の四隅を埋めやすい。

## 使い方

**動画を1本撮って、渡すだけ。**

```bash
python 01-01_calibrateCamera.py calib.mp4
```

**カメラを映したまま、その場で終わらせることもできる。** 動画ファイルは要らない。

```bash
python 01-01_calibrateCamera.py
```

**キーを押す必要は無い。** 盤の姿勢が変わるか、薄いマスが埋まるときだけ勝手に採り、
**画面の全マスが埋まったら自分で止まって解きにいく。**
窓には**まだ薄いマスが赤い枠で出る**ので、それを見ながら盤を運べばよい。
途中でやめるときは ESC か Ctrl-C。集まったぶんで解く。

**画面の無い機械（SSH 越しの走行体）でも動く。** 窓が開けなければ文字だけで同じことを言う。

```
  採った  7枚  **薄いマス 5**
  採った  8枚  **薄いマス 5**
```

画像の束でもフォルダでもよい。

```bash
python 01-01_calibrateCamera.py 'chess/*.png'
python 01-01_calibrateCamera.py chess/
```

**オプションは `--square_len` ひとつだけ。** 既定は同梱の `chessboard_a4.pdf`
（1マス 24.0mm・内側の角 9x6）。**A3 を刷ったときと、刷った紙の物差しが
100.0mm でなかったときだけ**渡す。

```bash
python 01-01_calibrateCamera.py calib.mp4 --square_len 34.0     # A3
```

### 動画の撮り方

**ゆっくり動かすこと。** 止め絵と違い、動画は必ずブレる。

1. 盤を**画面の四隅まで運ぶ**。歪みは縁で効くので、ここが埋まらないと決まらない
2. **寝かせ・起こし・左右へひねる**（±30〜45°）。
   正対ばかりだと**焦点距離と距離が分離できない**（どちらを変えても同じ絵になる）
3. 30〜60秒もあれば足りる

### 解像度は走行と同じにする（1280x720）

**歪みの係数そのものは解像度に依らない。** `k1 k2 p1 p2 k3` は正規化座標
（`(u-cx)/fx`）に掛かるため。**画素で表す `fx fy cx cy` だけが比例する**ので、
理屈の上では倍率を掛ければ移せる。

**だが2つの理由で、走行と同じ大きさで撮るのが唯一の安全な規則。**

**1. 多くの USB カメラは、解像度を変えると切り出し方まで変える。**
そうなると画角が別物になり、どう倍率を掛けても移せない。
**縮小か切り出しかは外から分からない。**

**2. 縮小しているだけでも、当てはめが荒くなる。** 同じ合成写真を 1280x720 と、
それを単純に縮小した 640x360 で解いた実測:

```
1280x720   fx 1249.7  hfov 54.24°  k1 -0.3587  k2 +0.1799  k3 -0.1668
 640x360   fx  624.0  hfov 54.30°  k1 -0.3228  k2 -0.2614  k3 +1.4088
```

`fx` はきれいに半分になり画角も合うが、**`k1` は 10% ずれ、`k2`/`k3` は符号ごと
変わっている**（角の位置の精度が落ち、高次の項が互いに融通し合うため）。
**切り出しが無い理想の場合ですらこれだけ動く。**

**要求した大きさではなく、実際に来た絵の大きさを記録している**ので、
`cap.set()` が黙って無視されても後から分かる。違っていれば警告が出る。

### 動画をどう間引いているか

**全部の枚は使わない。** 30fps なら隣り合う枚はほぼ同じで、**精度は上がらないのに
時間だけ増え、よく写った区間に重みが偏る。**

```
5枚おきに見る                          （毎秒6枚）
ブレている枚は捨てる                    （ラプラシアンの分散）
**姿勢が変わったか、薄いマスが埋まるとき**だけ採る
上限 40枚
```

実際に「同じ絵が30枚続く」動画で試すと、270枚 → 見た54枚 → **採った13枚**に絞り、
真の値（fx 1250.0 / k1 -0.350）を fx 1249.7 / k1 -0.3587 で当て直した。

**残差の悪い枚は秒で出る**ので、動画をその位置まで送れば何が悪かったか見られる。

## 読み方

* `残差 rms` が **0.5px 以下**なら素性がよい。1.0 を超えるなら、盤の反り・ぼけ・枚数を疑う
* **`縁が動く量`** が今回の目的。数十画素動くなら、目印の格子が成立しない原因はこれ。
  数画素しか動かないなら歪みは犯人ではない
* **`画角`** を `heading_reader.py` の `hfov 53.9°` と突き合わせる。
  大きく違えば、どちらかが間違っている
* **`画面の埋まり`** に薄いマスが残っているうちは、答えを信じない

## 確かめ方

わざと歪ませた合成写真で、元の値を当て直せることを確かめてある。

```
真の値    fx 1250.0  cx 640.0  cy 360.0  k1 -0.350   p1 +0.0010  p2 -0.0020
解いた値  fx 1250.3  cx 640.9  cy 359.0  k1 -0.3565  p1 +0.0011  p2 -0.0020
rms 0.087px
```

**射影変換では歪みを再現できない。** 4隅を歪んだ位置へ運んでも中は線形に埋まる。
先にきれいな透視図を作り、そのあと画素ごとに `remap` で歪ませること。

---


# Requirement 
* opencv-python 5.0.0.93 or later
* opencv-contrib-python 5.0.0.93 or later ※omnidirモジュールを使用する場合のみ

OpenCV 5系でPython APIに互換性のない修正が入ったため、サンプルは5系に合わせています。<br>
4系で動作させたい場合は[4.5.2.54対応版](https://github.com/Kazuhito00/OpenCV-CameraCalibration-Example/tree/d4805c7)を参照してください。
* `findChessboardCorners()`の戻り値形状が`(N, 1, 2)`から`(N, 2)`へ変更<br>
  ([1D and 0D array semantics](https://github.com/opencv/opencv/wiki/OpenCV-4-to-5-migration#1d-and-0d-array-semantics)に伴う変更)
* fisheyeの`CALIB_*`定数がcv名前空間へ統合(`cv.fisheye.CALIB_FIX_SKEW` → `cv.CALIB_FIX_SKEW`)<br>
  ([PR #23990](https://github.com/opencv/opencv/pull/23990)) ※定数の値自体も変更されているため注意

# Calibration Pattern
サンプルでは以下の7×10のチェスボード型のキャリブレーションパターンを使用します。
* http://opencv.jp/sample/pics/chesspattern_7x10.pdf

他の行列数のキャリブレーションパターンを使用したい場合は、以下を参照して作成or入手してください。
* https://docs.opencv.org/master/da/d0d/tutorial_camera_calibration_pattern.html
* https://github.com/opencv/opencv/blob/master/doc/pattern.png

また、以下のようなサークル型のパターンやセクターベース型のパターンのサンプルは用意していません。
* https://github.com/opencv/opencv/blob/master/doc/acircles_pattern.png
* https://docs.opencv.org/4.5.2/checkerboard_radon.png
  
# Usage
<img src="https://user-images.githubusercontent.com/37477845/122718897-6d98c800-d2a8-11eb-8d18-18cb6d2f0468.png" width="90%">
calibrateCameraのサンプルでキャリブレーションパラメータをcsvに保存し、<br>
undistortのサンプルで歪み補正を実施してください。

#### 01.calibrateCamera
```bash
python 01-01_calibrateCamera.py
python 02-01_fisheyeCalibrateCamera.py
python 03-01_omnidirCalibrateCamera.py
```
キャリブレーションパターン検出時にEnterを押すことで撮影します。<Br>
ESCを押すことでプログラムを終了し、キャリブレーションパラメータを保存します。<Br>

実行時には、以下のオプションが指定可能です。
<details>
<summary>オプション指定</summary>
   
* --device<br>
カメラデバイス番号の指定<br>
デフォルト：
    * 01-01_calibrateCamera：0
    * 02-01_fisheyeCalibrateCamera.py：0
    * 03-01_omnidirCalibrateCamera.py：0
* --file<br>
動画ファイル名の指定 ※指定時はカメラデバイスより優先し動画を読み込む<br>
デフォルト：
    * 01-01_calibrateCamera：None
    * 02-01_fisheyeCalibrateCamera.py：None
    * 03-01_omnidirCalibrateCamera.py：None
* --width<br>
カメラキャプチャ時の横幅<br>
デフォルト：
    * 01-01_calibrateCamera：640
    * 02-01_fisheyeCalibrateCamera.py：640
    * 03-01_omnidirCalibrateCamera.py：640
* --height<br>
カメラキャプチャ時の縦幅<br>
デフォルト：
    * 01-01_calibrateCamera：360
    * 02-01_fisheyeCalibrateCamera.py：360
    * 03-01_omnidirCalibrateCamera.py：360
* --square_len<br>
キャリブレーションパターン(チェスボード)の1辺の長さ(mm)<br>
デフォルト：
    * 01-01_calibrateCamera：23.0
    * 02-01_fisheyeCalibrateCamera.py：23.0
    * 03-01_omnidirCalibrateCamera.py：23.0
* --grid_size<br>
キャリブレーションパターン(チェスボード)の行列数(カンマ区切り指定)<br>
デフォルト：
    * 01-01_calibrateCamera：10,7
    * 02-01_fisheyeCalibrateCamera.py：10,7
    * 03-01_omnidirCalibrateCamera.py：10,7
* --k_filename<br>
半径方向の歪み係数の保存ファイル名(csv)<br>
デフォルト：
    * 01-01_calibrateCamera：K.csv
    * 02-01_fisheyeCalibrateCamera.py：K_fisheye.csv
    * 03-01_omnidirCalibrateCamera.py：K_omni.csv
* --d_filename<br>
円周方向の歪み係数の保存ファイル名(csv)<br>
デフォルト：
    * 01-01_calibrateCamera：d.csv
    * 02-01_fisheyeCalibrateCamera.py：d_fisheye.csv
    * 03-01_omnidirCalibrateCamera.py：d_omni.csv
* --xi_filename<br>
Mei'sモデルパラメータxiの保存ファイル名(csv)<br>
デフォルト：
    * 03-01_omnidirCalibrateCamera.py：xi_omni.csv
* --use_autoappend<br>
キャリブレーションパターン検出時に自動で撮影するか否か(指定しない場合はEnterで明示的に撮影)<br>
デフォルト：
    * 01-01_calibrateCamera：指定なし
    * 02-01_fisheyeCalibrateCamera.py：指定なし
    * 03-01_omnidirCalibrateCamera.py：指定なし
* --interval_time<br>
use_autoappend指定時の撮影間隔(ms)<br>
デフォルト：
    * 01-01_calibrateCamera：500
    * 02-01_fisheyeCalibrateCamera.py：500
    * 03-01_omnidirCalibrateCamera.py：500
</details>
  
#### 02.undistort
```bash
python 01-02_undistort.py
python 02-02_fisheyeUndistort.py
python 03-02_omnidirUndistort.py
```

実行時には、以下のオプションが指定可能です。
<details>
<summary>オプション指定</summary>
   
* --device<br>
カメラデバイス番号の指定<br>
デフォルト：
    * 01-01_calibrateCamera：0
    * 02-01_fisheyeCalibrateCamera.py：0
    * 03-01_omnidirCalibrateCamera.py：0
* --file<br>
動画ファイル名の指定 ※指定時はカメラデバイスより優先し動画を読み込む<br>
デフォルト：
    * 01-01_calibrateCamera：None
    * 02-01_fisheyeCalibrateCamera.py：None
    * 03-01_omnidirCalibrateCamera.py：None
* --width<br>
カメラキャプチャ時の横幅<br>
デフォルト：
    * 01-01_calibrateCamera：640
    * 02-01_fisheyeCalibrateCamera.py：640
    * 03-01_omnidirCalibrateCamera.py：640
* --height<br>
カメラキャプチャ時の縦幅<br>
デフォルト：
    * 01-01_calibrateCamera：360
    * 02-01_fisheyeCalibrateCamera.py：360
    * 03-01_omnidirCalibrateCamera.py：360
* --k_filename<br>
半径方向の歪み係数の読み込みファイル名(csv)<br>
デフォルト：
    * 01-01_calibrateCamera：K.csv
    * 02-01_fisheyeCalibrateCamera.py：K_fisheye.csv
    * 03-01_omnidirCalibrateCamera.py：K_omni.csv
* --d_filename<br>
円周方向の歪み係数の読み込みファイル名(csv)<br>
デフォルト：
    * 01-01_calibrateCamera：d.csv
    * 02-01_fisheyeCalibrateCamera.py：d_fisheye.csv
    * 03-01_omnidirCalibrateCamera.py：d_omni.csv
* --xi_filename<br>
Mei'sモデルパラメータxiの読み込みファイル名(csv)<br>
デフォルト：
    * 03-01_omnidirCalibrateCamera.py：xi_omni.csv
* --k_new_param<br>
Knewパラメータ指定時のスケール<br>
デフォルト：
    * 01-01_calibrateCamera：1.0
    * 02-01_fisheyeCalibrateCamera.py：0.9
    * 03-01_omnidirCalibrateCamera.py：0.5
</details>
  
# Reference
* [OpenCV Camera Calibration Tutorial](https://docs.opencv.org/master/dc/dbb/tutorial_py_calibration.html)
* [OpenCV Camera Calibration and 3D Reconstruction](https://docs.opencv.org/master/d9/d0c/group__calib3d.html)
* [OpenCV Fisheye camera model](https://docs.opencv.org/master/db/d58/group__calib3d__fisheye.html)
* [OpenCV Omnidirectional Camera Calibration](https://docs.opencv.org/master/dd/d12/tutorial_omnidir_calib_main.html)

# Author
高橋かずひと(https://twitter.com/KzhtTkhs)
 
# License 
OpenCV-CameraCalibration-Example is under [Apache-2.0 License](LICENSE).
