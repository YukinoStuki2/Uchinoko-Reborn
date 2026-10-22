# 揺れABPテンプレ(dev#19、WP: 揺れものpak生成の製品パイプライン結線)

## これは何か

`cooked/` 配下の40ファイル(10家系×F/M×{.uasset,.uexp})は、KawaiiPhysicsの
物理ノード(尻尾・耳L/R・スカーフ・エプロン紐)を追加した`ABP_{gender}_{family}
_Implimentation`(AnimBlueprint実装)である。**Palworldの既存AnimBlueprint
グラフを複製したものではない**——`D2PSwayAuthorFunctionLibrary`
(UEプロジェクト側、リポジトリ管理外)の`d2p_build_implementation_abp_from_spec`
がプログラム的にゼロから著作した自前生成アセット(noue開発の権利回避方針と
同じ考え方: `pipeline\py\noue_master\`の各種.uasset/.uexpと同種)。パッケージ
パス(`/Game/Pal/Blueprint/Character/Player/Imp_Cloth/ABP_*_Implimentation`)は
バニラの対応アセットと同名に揃えてあるが、これはMOD(オーバーライドpak)が
同じ論理パスへ差し替えることで有効化される標準的な手法であり、中身は
自前生成である。

`specs/` 配下の20 JSONは各テンプレのノード構成(root_bone列、target_abp等)を
記述する**構造メタデータ**。実行時のパッチ(`pipeline\py\sway_abp_build.py`)は
このJSONの`root_bone`のみを読み、`params`/`curves`はユーザーの揺れ強度選択
(job.json `sway_intensity`)から動的に再計算して上書きする——このJSON内の
`params`/`curves`値そのものは実行時には使われない(著作時点の記録として残す
のみ、gen_specs.pyが元々書き出した完全な形をそのまま保持)。

## 出所(2026-08-12時点)

**著作コードの所在**: `unreal\D2PSwayAuthor\`(2026-08-17 dev#1551で取り込み。
D2PSwayAuthorプラグインのC++ソース+著作/検証スクリプト+手順書
`unreal\D2PSwayAuthor\AUTHORING.md`)。

- ソース: `work\rd_19_tailmatch\abp\cooked\` / `work\rd_19_tailmatch\abp\specs\`
  (tailmatch3_fix WP、`work\rd_19_flight\notes_tailmatch3.md`。土台は
  `work\rd_19_hardset\abp\cooked\`/`specs\`(10家系×F/M)で、各テンプレの
  末尾に`NPC_GrassBoss001_Skin001_tail_01`(節数完全一致donor、dev#19
  TailMatch6Node)をroot_boneとする10本目(Maleは11本目、既存scarf_2込みの
  ため)のKawaiiPhysicsノードを追加著作した。既存9本(Femaleは8本)の
  root_bone・params・curvesは無改変。UAssetGUI tojsonでの解読検証
  OVERALL PASS済み(`work\rd_19_tailmatch\abp\inspect\verify_report_tailmatch3.txt`)。
  追加ノードのparams/curvesは「ふつう」(futsuu)プリセットの実値
  (damping=0.4, stiffness_tip=0.08, wdl/wdr_tip=0.55、既存OldCloth001系
  root同等)をそのまま流用し、値の新規発明はしていない(実行時は
  sway_abp_build.pyがjob.sway_intensityから全ノード一律で再計算・
  上書きするため、authored値自体は記録以上の意味を持たない)。
- **修正版チェック**: 本WP着手時点で `work\rd_19_tmplfix\cooked\` (dev#1396
  NameMap欠落根治のための再著作レーン)を確認したが、まだ存在しなかった
  (`work\rd_19_tmplfix\RESULT.md`が「調査フェーズ」のみ)ため、現行版を
  そのまま土台に採用した。

## 出所(2026-08-17追記、dev#1551 Lane P4: 服骨root6本の非アニメ骨差し替え)

`specs/`20本のうち服骨(F__/M_接頭、bivariant)root6本(OldCloth001_04/
Hunter001_14/OldCloth001_01/Ancient001_waistClothA_01/Kigurumi001_tail_01/
Hunter001_06)を、共有Skeleton(SK_PalHuman_Skeleton)上の非服骨(NPC__/
HeadEquip接頭、univariant、gendered=False)6本(NPC_SnowBoss_belt_01_l/_r、
HeadEquip046_hairA_01_l/_r、NPC_WorldTreeBoss001_skirtD_01_l、
NPC_GrassBoss001_Skin001_hat_cone_01)へ差し替えた。根拠: dev#1551
integI実測(`work\run_1551\integI\RESULT.md`)が「服骨root=プレイヤー
アニメ駆動で対anchor偏差が残存/非服骨root=床(偏差0)」を両検体・全14鎖で
例外なく確認しており、条件1(揺れ鎖の始点は親Humanoidボーンに対し相対位置
不変)を全鎖で満たすための構造工事。選定根拠・機械検証は
`work\run_1551\laneP4_notes\NOTES.md` §2・
`work\run_1551\laneP4_conv\select_roots.py`。

著作・cook手順は `unreal\D2PSwayAuthor\AUTHORING.md` のとおり(著作コード
自体は無改変)。**著作時の既知の落とし穴(本レーンで新規発見)**: 9/10ノードを
既に持つ既存ABPへ`d2p_build_implementation_abp_from_spec`を直接再実行すると、
ClothLayerグラフの旧ノード削除が効かず旧ノード+新ノードがCDOへ二重に
焼き込まれる(20テンプレ全てで再現、UAssetGUI tojsonで実測)。回避策:
対象ABPアセットを`unreal.EditorAssetLibrary.delete_asset()`で事前削除して
からfrom-specを呼ぶ(C++プラグイン自体は無改変、Python authoring
スクリプト側のワークアラウンド)。詳細: NOTES.md §4、
`work\run_1551\laneP4_conv\ue\`(author_batch.py/verify_batch.py/logs)。
検証: 20テンプレ全件の構造照合(KawaiiPhysics CDOブロック数・RootBone一致・
全パラメータ・全カーブキー・直列配線証拠)がOVERALL PASS。

この差し替えにより、下記「既知の欠陥(dev#1396)」節が指摘する
`{F,M}_Hunter001_14`のNameMap欠落問題は、そのroot_bone自体が
`NPC_SnowBoss_belt_01_r`へ置き換わったため当該スロットについては解消
(新rootは共有Skeleton4079骨カタログに実在確認済み、
`work\rd_19_donorcatalog\sk_palhuman_full.json`)。`M_Hunter001_17`
(恒久予備、どのスロットにも割り当てられない)は無変更のまま残存するが、
実際に評価されるノードではないため実害は無い(`sway_hub.py`
モジュールdocstring「予約骨」節参照)。

## 既知の欠陥(dev#1396、修正待ち)

`work\rd_19_scarffreeze\FIX.md`が機械検証済み: 全20テンプレのうち
`{F,M}_Hunter001_14`(scarf_1のroot_bone)と`M_Hunter001_17`(scarf_2の
root_bone、Maleのみ)の3骨名が、パッケージのNameMapに登録されていない
構造的欠陥がある。実機ではこの2ノード(scarf_1/scarf_2)が起動後約28秒で
物理破綻して凍結する(`work\rd_19_bonedump\RESULT.md`実測)。

**このWPではscarfノードを除去しない**(指揮者裁定2026-08-12: 「スカーフ
ノードを『欠陥があるから除去』しない、修正版で揺らすのが方針」)。根治は
別レーン(`work\rd_19_tmplfix\`)がNameMap登録込みで再著作したテンプレを
生成し、本ディレクトリの`cooked/`+`specs/`をその出力で差し替えることで
行われる想定(`pipeline\py\sway_abp_build.py`側のコードはテンプレの
root_bone列・ノード数・ファイル一覧を一切ハードコードしていないため、
このディレクトリの中身を差し替えるだけで自動的に反映される)。

## テンプレ更新手順(将来、tmplfixレーン完了後)

1. `work\rd_19_tmplfix\cooked\*.{uasset,uexp}` を `cooked/` へ上書きコピー
2. 対応する `work\rd_19_tmplfix\specs\*.json`(または再生成した spec)を
   `specs/` へ上書きコピー
3. `python -m pytest pipeline\py\test_sway_abp_build.py -q` で構造検証
   (root_bone解決・パッチ・往復検証)が通ることを確認
4. 本READMEの「出所」節を更新
