# IORN-007 Phase-1 レビューと次の一手

**日付:** 2026-08-07
**対象:** `D:\DevGit\ct_dosemc_core` @ `666773c`（Phase-0 完了 + Phase-1 初回アンカー）
**査読者:** Claude (claude-opus-5) / Cowork
**根拠:** リポジトリ実物（`ct_dosemc_core/*.py`, `tools/run_validation.py`, `docs/MC_SOURCE_MODEL.md`, `results/phase1_ctdi_anchor_120kV_32cm_NT2cm_1e9.json`）、`vendor/MCGPU` のソース実物、および公開文献

---

## 0. 結論（先に）

**Phase-1 は「不合格」ではありません。「合格基準の選び方が間違っている」だけです。**

Cursor の報告書 "The honest verdict: the anchor does not yet pass" は誠実ですが、
比較先が誤っています。いま構築されている系は

* bowtie なし・フラットファン
* 均質 PMMA 円柱、直径 320 mm
* 点線源、SAD 600 mm
* 120 kVp W/Al スペクトル
* PMMA への吸収線量（空気カーマではない）

であり、これは **実在スキャナの測定 CTDIvol とは原理的に比較不能**です。centre/peripheral = 0.293 を
「文献の ~0.5」と比べて落第としていますが、文献値はすべて bowtie 付き実機の値なので、
この比較自体が成立しません。

一方でこの構成は、**AAPM TG-195 Case 4 の仕様とほぼ完全に一致します**。
TG-195 は bowtie なし・同一形状・同一 SAD・同一スペクトルで、複数の独立 MC コードによる
リファレンス値が公開されている、CT 線量 MC の事実上の code-verification 標準です。

> 提案：**Phase-1 のゲートを「実測 CTDIvol の再現」から「TG-195 Case 4 の再現」に差し替える。**
> 実測 CTDIvol の再現は bowtie 近似が入った後（Phase-1b）に後ろ倒しする。

これで、報告書が挙げた 5 つのブロッカー（bowtie、PMMA→空気カーマ、収束、CPU/GPU、σ）のうち
**上位 2 つが Phase-1 の合格要件から外れます**。どちらも TG-195 Case 4 には存在しない問題だからです。

---

## 1. TG-195 Case 4 が現状構成と一致することの根拠

AAPM Report No. 195 *Monte Carlo Reference Data Sets for Imaging Research*
（Sechopoulos et al., Med. Phys. 42, 5679, 2015 / 報告書 PDF は AAPM から無償公開）
Case 4 "Computed Tomography with Simple Solids", §3.4（pp. 25–26）, §4.4（pp. 45–48）より引用：

> "Body phantom is a cylinder of height (z-direction) 3,000 mm (to approximate an infinite cylinder) and radius 160 mm"

> "The body phantom is made of PMMA. The rest of the geometry is filled with air."

> "The rotation radius of the x-ray source about the isocenter, located at the center of the body phantom, is 600 mm."

> "The source is an isotropic x-ray point source collimated to a fan beam with dimensions, measured at the center of the body phantom, of width (y-direction) equal to the body diameter (320 mm) and thickness (z-direction) of t."

> "For the second test, the scoring is the energy deposited in two 10 mm diameter PMMA cylinders with height (z-direction) of 100 mm from −50 mm to +50 mm"（一方は中心、他方は中心から 150 mm）

> "Simulations are performed for the W/Al 120 kVp spectrum and for monoenergetic photons with energy 56.4 keV (equivalent to the mean energy of the spectrum)."

> "Source rotated 360° about the isocenter in 10° increments, with 36 evenly spaced simulations performed"

> 統計誤差は "1% or lower on all scored quantities at each VOI"

（上記は PDF から取得した引用。**採用前に Cursor が原文 PDF の該当ページで一字一句照合すること。**
本文書の引用は一次確認済みではなく、二次取得です。）

### 現状コードとの対応

| TG-195 Case 4 | 現状 `ct_dosemc_core` | 差分 |
|---|---|---|
| PMMA 円柱 半径 160 mm | `CtdiPhantomSpec(diameter_cm=32.0)` | **一致** |
| 高さ 3,000 mm | `length_cm=15.0` | 引数変更のみ |
| SAD 600 mm | `--sad 60` | **一致** |
| bowtie なし・等方点線源をファンに絞る | フラットファン、`Omega = 2 sin(θ/2)·φ` | **一致（現状の"欠陥"がここでは仕様）** |
| スコアリング = 直径 10 mm・長さ 100 mm の PMMA 円柱、中心と r=150 mm | `chamber_diameter_cm=1.31`, `chamber_length_cm=10.0`, `chamber_depth_cm=1.0`（= r 150 mm） | **半径位置は一致**、直径を 1.31→1.00 cm に変更するだけ |
| 単位 = eV per initial photon | `region_dose(...)` が eV/g/history を保持 | 質量を掛けるだけ、**mAs 正規化不要** |
| 120 kVp W/Al スペクトル配布 + 単色 56.4 keV | SpekPy 生成スペクトル | TG-195 スペクトルを読む経路を追加 |

**注目すべき点：**

1. **bowtie が不要になる。** TG-195 Case 4 に bowtie は無い。現状の「最大の既知バイアス」が、
   ここでは仕様そのもの。
2. **PMMA→空気カーマ変換が不要になる。** TG-195 は PMMA への付与エネルギーを直接スコアする。
3. **絶対正規化（SpekPy の絶対出力への依存）が不要になる。** 単位が「入射光子あたり」なので、
   `N_Omega`・`Omega`・mAs の連鎖がまるごと検証対象から外れる。
   → SpekPy の絶対出力が正しいかという未解決問題を、この段階では切り離せる。
4. **単色 56.4 keV ケースがある。** スペクトルサンプリング・リビニング（255 bin 制約）を
   完全に排除した状態で輸送だけを検証できる。デバッグの切り分けとして極めて強力。
5. **σ の議論に外部基準が入る。** TG-195 は複数コードの結果とその散らばりを与えるので、
   「7.2 倍」問題の妥当性を外から検定できる。

---

## 2. 検証できたこと（Cursor の主張の裏取り）

### 2.1 MC-GPU の aperture 順序バグ — **ソースで確認、指摘は正しい**

`vendor/MCGPU/MC-GPU_v1.3.cu` を実機上で直接確認しました。

```
1351:  // Read input fan beam polar (theta) and azimuthal (phi) aperture angles (deg):
1352:  double phi_aperture, theta_aperture;
1353:  sscanf(new_line, "%lf %lf", &phi_aperture, &theta_aperture);
```

コメントは "polar (theta) and azimuthal (phi)" の順と読めますが、`sscanf` の代入先は
**phi（方位角）が先、theta（極角）が後**。サンプル入力ファイルのコメントに従うと、
Z 方向が開き切ったビームになります。Cursor の指摘は正確で、上流に報告する価値があります。

なお、エンジン自身のエコーは正しい順序で出ています：

```
509:  printf("      azimuthal (phi), polar apertures = %.6f , %.6f degrees\n", ...)
```

`McgpuRun.assert_apertures()` がこの行を読み返して検証しているのは正しい設計です。

### 2.2 立体角の式 — **ソースの実装と一致**

```
1378:  source_data[0].cos_theta_low = (float)( cos((90.0 - 0.5*theta_aperture)*DEG2RAD) );
1379:  source_data[0].D_cos_theta   = (float)( -2.0*source_data[0].cos_theta_low );
1380:  source_data[0].phi_low       = (float)( (90.0 - 0.5*phi_aperture)*DEG2RAD );
1381:  source_data[0].D_phi         = (float)( phi_aperture*DEG2RAD );
```

`D_cos_theta = -2 cos(90° − θ/2) = 2 sin(θ/2)`、`D_phi = φ[rad]`。
`source_model.BeamGeometry.solid_angle_sr` の `2·sin(θ_ap/2)·φ_ap` はこれと厳密に一致。
数値も再計算して一致（θ=1.9097° → 0.033330、φ=32.932° → 0.574776 rad、積 0.0191564 sr）。

### 2.3 報告数値の内部整合性 — **すべて再計算して一致**

* CTDIw = 4.155/3 + 2×14.181/3 = **10.839 mGy** ✓
* free-in-air kerma = 88.763 µGy/mAs × (100/60)² × 100 mAs = **24.656 mGy** ✓
* 4 チャンバの標本 SD = 0.00866 mGy → 平均の標準誤差 0.00433… ではなく
  `np.std(ddof=1)/√4` = **0.00433 mGy**、引用 σ 0.000601 mGy に対し **7.2 倍** ✓

### 2.4 幾何チェックの妥当性

`geometric_fwhm_cm = beam.beam_width_at(SAD − r_peripheral)` = 45 cm 地点での幅 = 1.500 cm。
測定 FWHM も 1.500 cm。**これは正しい期待値**です — 12時チャンバへの寄与は、線源が同方位に
来たとき（距離 45 cm、PMMA 通過 1 cm）が圧倒的に支配的で、反対側（距離 75 cm、PMMA 31 cm、
透過率 ~10⁻³）はピークに寄与しないため。ただし後述 3.3 の限界があります。

---

## 3. 新規指摘（Cursor がまだ拾っていないもの）

### 3.1 【重】σ の「7.2 倍」は点推定として弱い

4 点の標本 SD は自由度 3。σ の相対不確かさは約 √(1/(2·3)) ≈ **41%** あります。
つまり「7.2 倍」は実際には **おおむね 4〜13 倍**の幅を持つ推定であり、
論文に「7.2×」と書くと過剰な精度主張になります。

対応：`docs/MC_SOURCE_MODEL.md` §6-5 の replica 法（K 本の独立シード run の標本 SD）へ即座に移行。
K ≥ 10 なら σ の相対不確かさは 23% 以下。TG-195 Case 4 は 1 run が軽いので K=20 も現実的です。
当面の報告は「4 点散布から σ は引用値の 4〜13 倍と推定される」と区間で書くべきです。

### 3.2 【重】SpekPy の空気減弱の既定挙動を確認していない

`normalisation.photons_per_sr_per_mas` の assumption に
"inverse-square law with no air attenuation between focus and z" とありますが、
SpekPy が `z`（既定 100 cm）までの空気パスを内部で掛けているかどうかを検証した形跡がありません。
掛けているなら `Φ(z)·z²` は真の N_Ω を **過小評価**し（120 kVp・1 m 空気で数 % オーダー）、
絶対線量に系統誤差が入ります。

対応：`spekpy.Spek(...)` の同一設定で `z=1 cm` と `z=100 cm` の
`get_flu()·z²` を比較する単体テストを 1 本追加。一致しなければ空気減弱込み。
`tests/` の anti-fabrication パターンと同じ思想で、**assumption を主張ではなく検定にする**。

> TG-195 Case 4 に移れば、この問題は Phase-1 合格要件から外れます（入射光子あたりで正規化するため）。
> ただし Phase-2 の mGy には必ず効くので、宿題としては残ります。

### 3.3 FWHM チェックは「入射側のみ」の検証にとどまる

3.4 で述べたとおり、この FWHM は線源が近い ±30° 程度のガントリ角にしか感度がありません。
`--projections 1`（単一投影・回転なし）の run を 1 本追加し、そこで
Z 方向プロファイル幅とファン方向の照射幅を**両方**幾何予測と突き合わせるべきです。
1 投影なら数分で終わり、ビーム定義の誤りを回転平均で隠さずに検出できます。

### 3.4 bowtie の実装方針：ジオメトリ内のくさびではなく「ファン分割」を推奨

`docs/MC_SOURCE_MODEL.md` §4.2 の計画は「アルミのくさびを幾何に置く」ですが、
MC-GPU はボクセル幾何しか持たないため、線源近傍にくさびを置くにはボクセル格子を
線源まで拡張する必要があり、コストが跳ね上がります。

**代替案（推奨）: sub-fan decomposition**

1. ファン開口 φ を K 個（K = 10〜20）の細い扇形に分割する。
2. 各 sub-fan k の中心ファン角 φ_k における bowtie 透過長 t(φ_k) を、フィットした
   プロファイルから求める。
3. SpekPy スペクトルを t(φ_k) 分の bowtie 材で減弱させ、**sub-fan ごとのスペクトル** S_k を作る。
4. sub-fan ごとに MC-GPU を走らせ（開口 φ/K）、線量マップを
   重み N_k = N_Ω(S_k) · Ω_k · mAs で加算する。
5. σ は sub-fan 間で独立なので二乗和で合成できる（しかもこれは**正しい**独立性）。

この方式の利点：

* **フルエンス整形とオフアクシス線質硬化の両方**が自動的に入る（§4.2 が挙げた 2 つの効果）。
* 総ヒストリ数は変わらない（各 sub-fan が 1/K）。
* bowtie 形状はプロファイル 1 本（角度 → 等価厚み）に還元されるので、
  **プロファイルそのものを `results/` の機械可読データとして公開できる** — openness の論拠が強くなる。
* MC-GPU 本体に一切手を入れない（vendor をバイト同一に保つ方針と整合）。

bowtie プロファイルのフィット先としては、実測 HVL のファン角依存性
（中心ビームと周辺ビームの HVL 差）と、free-in-air フルエンスの角度依存性の
公開値を使う。ここは openly-licensed なデータ源の確保が別途必要です。

### 3.5 μen/ρ 変換：局所スペクトル平均が必要な点を明示すべき

`(μen/ρ)_air / (μen/ρ)_PMMA` は 30 keV 付近と 80 keV 付近で数 % 変わります。
NIST（Hubbell & Seltzer, NISTIR 5632 — 米国政府著作物でパブリックドメイン）から
元素データ＋混合則で計算する方針は正しいですが、**どのスペクトルで平均するか**が問題。
MC-GPU は局所スペクトルをタリーしないため、厳密には計算できません。

対応：一次線の局所スペクトル（線源スペクトル × 経路の減弱）で平均する近似を実装し、
散乱線の寄与による変動幅を**感度として区間で報告**する。
「係数 = 0.9xx（0.9yy–0.9zz、局所平均エネルギー 45–75 keV の範囲）」という書き方にすれば、
査読で刺されません。TG-195 Case 4 のゲートには不要です。

### 3.6 ライセンス：TG-195 データは「利用可・再配布不可」

AAPM Report No. 195 は無償で公開されていますが、"© 2015 by American Association of
Physicists in Medicine. All rights reserved." です。
**TCIA の DICOM と同じ扱いにしてください** — ダウンロードして使うのは可、リポジトリにコミットは不可。

対応：`tools/fetch_tg195.py`（URL・取得日・SHA-256 を `PROVENANCE.json` に記録して検証、
ファイル自体は `.gitignore`）。`MCGPU_materials` と `make_materials.py` で既に確立している
パターンをそのまま流用できます。

### 3.7 上流への報告を成果物にする

MC-GPU v1.3 の 2 件（バイナリを text mode で開く / CPU 分岐で PRNG が投影間で進まない）は
どちらも**サイレントに誤結果を出す**欠陥です。DIDSR/MCGPU に issue を立て、
その URL を論文の Acknowledgements か Data Availability に置いてください。
「openness を主張する論文が、依拠したオープンソースの欠陥を上流に返した」というのは、
モートそのものの実証になります。これは査読者が好みます。

---

## 4. 改訂 Phase-1 ゲート（実行順）

現行 `docs/MC_SOURCE_MODEL.md` §6 を、以下で置き換えることを提案します。

### Phase-1a — code verification（TG-195）※ここが新しいゲート

| # | 内容 | 合格基準 |
|---|---|---|
| G0 | TG-195 **Case 1**（HVL）を再現 | 参照値と 1σ 以内。SpekPy + 材料断面積 + 輸送の同時検証 |
| G1 | TG-195 **Case 4 / 単色 56.4 keV / 単一投影** | 参照値と 2% 以内。スペクトル要因を排した純輸送検証 |
| G2 | TG-195 **Case 4 / 120 kVp W/Al / 36 投影** の 2 本の PMMA 円柱 | 参照値のコード間ばらつきの範囲内 |
| G3 | ボクセルサイズ収束（0.25 / 0.125 cm）と投影数収束（36 / 180 / 360） | 変化が G2 の許容幅より小さい |
| G4 | replica 法（K ≥ 10、独立シード）による σ | 4 点散布法と整合、二乗和法との比を報告 |
| G5 | CPU / GPU 一致 | G2 の全量で統計誤差内 |

**G0–G2 に bowtie も μen/ρ も絶対 mAs 正規化も不要**です。いま止まっている理由が消えます。

### Phase-1b — physical anchor（実測 CTDIvol）

| # | 内容 | 合格基準 |
|---|---|---|
| G6 | bowtie 近似（§3.4 の sub-fan 方式）実装、プロファイルとフィット残差を `results/` に公開 | — |
| G7 | 添加濾過を実測 HVL に合わせて調整、HVL1/HVL2 を報告 | 公開 CT の HVL 範囲内 |
| G8 | PMMA → 空気カーマ変換（NIST、混合則、感度区間つき） | — |
| G9 | CTDIw / CTDIvol を公開値・実測値と比較 | 誤差と bowtie 感度を明示して報告（「一致」を主張しない選択も可） |

### Phase-2 解禁条件

**G0–G5 の合格**をもって Phase-2（患者コホート）を解禁する。
G6–G9 は Phase-2 と並行で構わない — 患者線量の正規化は
「DICOM/RDSR 記録の CTDIvol に合わせる」方式（`MC_SOURCE_MODEL.md` §4.5 が既に挙げている）を
採れば、bowtie の絶対値への依存を大きく落とせるためです。
ただしその場合、**bowtie がフルエンスの半径分布に与える影響**は残るので、
G6 の感度解析は論文までに必ず必要です。

---

## 5. Cursor への指示（この順で、終わったら報告）

```
1. docs/MC_SOURCE_MODEL.md §5 と §6 を、本レビューの「改訂 Phase-1 ゲート」で書き換える。
   Phase-1 の合格基準が TG-195 Case 1 / Case 4 であることを明記。
   現行 §5.2 の「dimensionless comparisons」節は、bowtie 付き実機との比較が
   成立しない理由を追記したうえで Phase-1b に移す。

2. AAPM Report No. 195 の PDF と電子リソースを取得し、本レビュー §1 の引用を
   原文の該当ページで一字一句照合する。相違があれば報告すること。
   ファイルはリポジトリにコミットしない（© AAPM, All rights reserved）。
   tools/fetch_tg195.py を作り、URL・取得日・SHA-256 を data/PROVENANCE.json に記録。

3. ct_dosemc_core/tg195.py を新設：
   - Case 1 (HVL) と Case 4 の幾何・材料・スコアリング領域を、
     TG-195 の仕様値をコード内定数として持つ（数値は仕様であって転載データではない）
   - TG-195 配布スペクトルを読む Reader（SpekPy 経路と切り替え可能に）
   - 単位変換：eV/g/history × 領域質量 → eV per initial photon
   既存の CtdiPhantomSpec / build_ctdi_phantom は引数変更で流用できるはず。

4. tools/run_tg195.py を新設し、G0 → G1 → G2 の順に実行。
   G1（単色 56.4 keV、単一投影）を最優先で回すこと。ここが合わなければ他は全部無意味。

5. 3.3 の単一投影ビーム幾何チェックを tools/run_validation.py に組み込む
   （--projections 1 のときは回転平均でなく素の幾何と突き合わせる）。

6. 3.2 の SpekPy 空気減弱テストを tests/ に 1 本追加。

7. DIDSR/MCGPU に issue を 2 件立てる（text-mode fopen / CPU 分岐の PRNG）。
   issue URL を docs/MC_SOURCE_MODEL.md §2.1 に記録。

8. STOP して報告：G0/G1/G2 の数値と TG-195 参照値の比、および残る差分の原因仮説。
```

**bowtie・μen/ρ・患者データには、G0–G2 が出るまで一切触らないこと。**

---

## 6. 付記：論文（PMB）への効き方

PMB の査読者が MC 線量計算論文でまず確認するのは、実測一致ではなく
**code verification が済んでいるか**です。TG-195 は 2015 年以降その事実上の標準で、
「TG-195 Case 1 と Case 4 に合致」と書けるかどうかで初稿の通り方が変わります。

さらに IORN-007 のモート（openness × provenance × multi-vendor）との相性が良い：

* TG-195 のリファレンスは **公開・無償**。査読者が自分で確認できる。
* MC-GPU（パブリックドメイン）＋ TG-195（公開リファレンス）＋ MIT ラッパ＋ CC-BY TCIA という
  鎖が、**端から端まで検証可能**になる。
* 「係数が非公開だから独自に計算した」という主張に、
  「その独自計算は公開リファレンスで検証済み」という裏付けが付く。
  これが無いと、独自計算はただの未検証コードです。

一方で Nuntue et al. 2025 (`10.1002/acm2.70321`) は測定による検証を持っています。
IORN-007 は測定を持たないので、**検証の軸を「実測一致」ではなく「公開リファレンス一致 ＋
全経路の検証可能性」に置く**のが、勝てる土俵の選び方です。Introduction と Validation の
書き方をその線で統一してください。

---

## 参考文献（引用箇所つき）

**AAPM Report No. 195** — Sechopoulos I. et al., *Monte Carlo reference data sets for
imaging research: Executive summary of the report of AAPM Research Committee Task Group 195*,
Med. Phys. **42**(10), 5679–5691 (2015). 報告書 PDF: https://www.aapm.org/pubs/reports/RPT_195.pdf
電子リソース: https://www.aapm.org/pubs/reports/report195.asp

> "Body phantom is a cylinder of height (z-direction) 3,000 mm (to approximate an infinite cylinder) and radius 160 mm"（§3.4, p.25）
> "The rotation radius of the x-ray source about the isocenter, located at the center of the body phantom, is 600 mm."（§3.4, p.25）
> "For the second test, the scoring is the energy deposited in two 10 mm diameter PMMA cylinders with height (z-direction) of 100 mm from −50 mm to +50 mm"（§3.4, p.26）
> "Simulations are performed for the W/Al 120 kVp spectrum and for monoenergetic photons with energy 56.4 keV (equivalent to the mean energy of the spectrum)."（§3.4, p.26）
> "Detailed tabular results for all six cases simulated with the Monte Carlo packages listed in Table 2 are available for download in the electronic resources included with this report"（p.32）

**MC-GPU v1.3 ソース**（DIDSR/FDA, パブリックドメイン） — `vendor/MCGPU/MC-GPU_v1.3.cu`

> `1351:  // Read input fan beam polar (theta) and azimuthal (phi) aperture angles (deg):`
> `1353:  sscanf(new_line, "%lf %lf", &phi_aperture, &theta_aperture);`

> `1379:  source_data[0].D_cos_theta   = (float)( -2.0*source_data[0].cos_theta_low );      // Theta aperture is symetric above and below 90 deg`
> `1381:  source_data[0].D_phi         = (float)( phi_aperture*DEG2RAD );`

**Badal A., Badano A.**, *Accelerating Monte Carlo simulations of photon transport in a
voxelized geometry using a massively parallel Graphics Processing Unit*,
Med. Phys. **36**(11), 4878–4880 (2009).

**Hubbell J.H., Seltzer S.M.**, *Tables of X-Ray Mass Attenuation Coefficients and Mass
Energy-Absorption Coefficients*, NISTIR 5632（米国政府著作物・パブリックドメイン）.
https://physics.nist.gov/PhysRefData/XrayMassCoef/cover.html

**AAPM Report No. 246** — *Estimating Patient Organ Dose with Computed Tomography*.
https://www.aapm.org/pubs/reports/RPT_246.pdf （Phase-3 の比較対象整理に使える無償資料）
