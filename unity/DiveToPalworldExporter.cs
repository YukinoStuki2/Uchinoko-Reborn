// DiveToPalworld用: アバターのprefabから変換に必要な一式を書き出す
//   - 統合FBX(NDMFベイク後・activeのみを1本に書き出したもの)
//   - humanoid.json (人型ボーン対応表、ベイク後の実体から)
//   - 各メッシュ×マテリアルスロットの実テクスチャ(PNG) + material_map.json
//
// 仕様(2026-07-21ぱん裁定): prefab→palは「そのプレハブをシーンに置いた時点での
// 見た目」を持ってくる。つまり:
//   - Inactiveなオブジェクト・無効なレンダラーは持ってこない
//   - Modular Avatarで着せた服(D&D構成)はNDMFベイク後の見た目で持ってくる
// このため元FBXのコピーではなく、ベイク済み実体を com.unity.formats.fbx の
// ModelExporter で1本のFBXへ統合書き出しする(複数FBX構成もこれで自然に解決)。
//
// 使い方(GUI):
//   1. このファイルを Assets/Editor/ に入れる(FBX Exporterパッケージ必須)
//   2. Projectビューでアバターのprefabを選択(またはHierarchyでルートを選択)
//   3. メニュー Tools > DiveToPalworld > Export Avatar
//   4. 出力フォルダごと DiveToPalworld へ(中のFBXをD&D)
//
// バッチ(開発用):
//   Unity.exe -batchmode -projectPath <proj> -executeMethod DiveToPalworldExporter.ExportBatch
//     -vrm2palPrefab <Assets/....prefab> -vrm2palOut <出力フォルダ> -quit
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;

public static class DiveToPalworldExporter
{
    [MenuItem("Tools/DiveToPalworld/Export Avatar")]
    static void ExportMenu()
    {
        var target = Selection.activeGameObject;
        if (target == null)
        {
            EditorUtility.DisplayDialog("DiveToPalworld",
                "アバターのprefab(またはHierarchyのルート)を選択してください", "OK");
            return;
        }
        string outDir = EditorUtility.SaveFolderPanel(
            "書き出し先フォルダ(空フォルダ推奨)", "", target.name + "_vrm2pal");
        if (string.IsNullOrEmpty(outDir)) return;
        try
        {
            Export(target, outDir);
            EditorUtility.DisplayDialog("DiveToPalworld",
                "書き出しました:\n" + outDir +
                "\n\nこのフォルダの中のFBXをDiveToPalworldへD&Dしてください", "OK");
            EditorUtility.RevealInFinder(outDir);
        }
        catch (Exception e)
        {
            EditorUtility.DisplayDialog("DiveToPalworld", "失敗: " + e.Message, "OK");
            Debug.LogException(e);
        }
    }

    // 開発・自動テスト用エントリポイント
    public static void ExportBatch()
    {
        string prefabPath = GetArg("-vrm2palPrefab");
        string outDir = GetArg("-vrm2palOut");

        // dev#518診断: prefabパス解決の構造を成功/失敗にかかわらず必ずログへ残す。
        // GUID未登録(=空文字列)ならインポート未完了を示唆、生バイトは全角/大文字
        // 小文字の混入を機械的に見分けるため(問い合わせでは実物のprefabを
        // 送ってもらえないので、ログだけで判別できる必要がある)
        string guid = AssetDatabase.AssetPathToGUID(prefabPath);
        Debug.Log("D2P: prefab resolve path=" + prefabPath +
                  " guid=" + (string.IsNullOrEmpty(guid) ? "(empty=GUID not registered)" : guid) +
                  " rawBytes=" + BitConverter.ToString(Encoding.UTF8.GetBytes(prefabPath)));

        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
        if (prefab == null)
        {
            // 初回失敗時のみ: AssetDatabase.Refresh()で解消するかを記録して再試行する
            Debug.LogWarning("D2P: initial prefab load failed; retrying via AssetDatabase.Refresh: " + prefabPath);
            AssetDatabase.Refresh();
            prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
            Debug.Log("D2P: retry result after Refresh: " + (prefab != null ? "succeeded (resolved)" : "failed (not resolved)"));
        }
        if (prefab == null) throw new Exception("cannot read prefab: " + prefabPath);
        // dev#696: ExportBatch()自体には最上位のtry/catchが無く、Export()内の
        // Reflection呼び出し以外の箇所(ExportHumanoid/EnsureUniqueTransformNames等)
        // で未捕捉の例外が飛ぶと、Unity既定の例外ロギング挙動に頼るしかなかった。
        // 既定挙動がどこまでスタックトレースを書き出すかはUnity内部実装依存で
        // 保証が無い(dev#518の実報告では「NullReferenceException」+
        // 「Rethrow as TargetInvocationException」の2行しかログに残らず、
        // 実際にどのメソッドで落ちたか特定できなかった)。
        // ここでe.ToString()(型名・メッセージ・スタックトレース・InnerException
        // 連鎖を全て含む再帰的な文字列)を「D2P:」プレフィックス付きで確実に
        // 1回ログへ書き出す。ps1側の抜粋パターン("Exception|error CS")には
        // 「D2P:」行自体も(型名に"Exception"を含むため通常は)一致するので、
        // 抜粋の後続文脈(-Context)にスタックトレース全体が確実に乗る。
        // throw; で再スローするため D2P_EXPORT_DONE は書かれず、失敗判定
        // (export_from_unity.ps1の$doneチェック)への影響は無い。
        try
        {
            Export(prefab, outDir);
        }
        catch (Exception e)
        {
            Debug.LogException(e);
            Debug.Log(BuildExportBatchFailureLog(e));
            throw;
        }
        Debug.Log("D2P_EXPORT_DONE " + outDir);
    }

    // D2P_EXPORTBATCH_FAILLOG_PURE_BEGIN
    // Export()から飛んできた未捕捉例外を、D2P:プレフィックス付きの1本の
    // ログ文字列へ整形する(dev#696)。e.ToString()はException型の標準実装として
    // 型名・メッセージ・スタックトレースに加え、InnerExceptionが有る場合は
    // 「 ---> (InnerExceptionのToString) 」を再帰的に連結する(.NET/Mono共通仕様)。
    // 独立した純粋関数にしているのは、Unity(GameObject等)に依存せず
    // dotnetハーネスで直接コンパイル・実行して振る舞いを検証できるようにするため
    // (tests/unity_exporter/test_thirdparty_init_guard.pyと同じ抽出方式)。
    internal static string BuildExportBatchFailureLog(Exception e)
    {
        return "D2P: an exception occurred during Unity export, aborting export: " + e.ToString();
    }
    // D2P_EXPORTBATCH_FAILLOG_PURE_END

    static string GetArg(string name)
    {
        var args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
            if (args[i] == name) return args[i + 1];
        throw new Exception("missing argument: " + name);
    }

    static void Export(GameObject target, string outDir)
    {
        Directory.CreateDirectory(outDir);
        // NDMFベイクとinactive除去で破壊的に変更するため、常に複製を処理する
        GameObject instance;
        if (target.scene.IsValid())
        {
            instance = UnityEngine.Object.Instantiate(target);
            instance.name = target.name;  // "(Clone)"を除去
        }
        else
        {
            instance = (GameObject)PrefabUtility.InstantiatePrefab(target);
            // 子の削除を許すため完全アンパック
            PrefabUtility.UnpackPrefabInstance(instance,
                PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
        }
        try
        {
            instance.SetActive(true);
            instance.transform.localPosition = Vector3.zero;      // 出力座標系を安定させる
            instance.transform.localRotation = Quaternion.identity;
            instance.transform.localScale = Vector3.one;
            D2PDiagDump(instance, "00 before StripNonWhitelistedPreBake");
            D2PDiagShot(instance, outDir, "00_front", "front");
            D2PDiagShot(instance, outDir, "00_side", "side");
            D2PDiagShot(instance, outDir, "00_isolated_beret_ribbon", "front", new[] { "Beret", "Ribbon", "Body" });
            StripNonWhitelistedPreBake(instance);                 // ①-a 第1段: VRC/MA/NDMF本体+必須5型以外を除去(BakeNdmfの直前必須)
            D2PDiagDump(instance, "01 after StripNonWhitelistedPreBake / before BakeNdmf");
            CleanupClothesBonesPreBake(instance);                 // ①-a' dev#1551 laneC: 服armature配下の無ウェイト骨をMA処理前に削除(汚染源の根治、BakeNdmfの直前必須)
            D2PDiagDump(instance, "01b after CleanupClothesBonesPreBake / before BakeNdmf");
            BakeNdmf(instance);                                   // ① MA等を適用
            try
            {
                WriteA2Snapshot(instance, outDir);                // ①' dev#1551(postma-snapshot): 二層オラクルのA2(MA処理直後のUnityヒエラルキー)をサイドカーへ出す。以降の破壊的処理より前でなければならない
            }
            catch (Exception e)
            {
                Debug.LogWarning("D2P: WriteA2Snapshot failed (" + e.GetType().Name + ": " + e.Message +
                    ") — a2_bones.json/a2_vertices.json may be missing or incomplete; export continues (fail-open, dev#1551 postma-snapshot)");
            }
            D2PDiagDump(instance, "02 after BakeNdmf");
            D2PDiagShot(instance, outDir, "02_front", "front");
            D2PDiagShot(instance, outDir, "02_side", "side");
            D2PDiagShot(instance, outDir, "02_isolated_beret_ribbon", "front", new[] { "Beret", "Ribbon", "Body" });
            StripConstraints(instance);                           // ①' Constraint除去(輸出専用複製のみ)
            D2PDiagDump(instance, "03 after StripConstraints");
            StripInactive(instance);                              // ② 見えない物を除去
            D2PDiagDump(instance, "04 after StripInactive");
            D2PDiagShot(instance, outDir, "04_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            ConvertStaticMeshesToSkinned(instance);               // ②-a 非スキンメッシュをSkinnedMeshRenderer化(以降の全工程を一様化)
            D2PDiagDump(instance, "04b after ConvertStaticMeshesToSkinned");
            D2PDiagShot(instance, outDir, "04b_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            FlattenSkinnedMeshes(instance);                       // ②' 頂点をバインド時ワールドへ
            D2PDiagDump(instance, "05 after FlattenSkinnedMeshes");
            D2PDiagShot(instance, outDir, "05_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            var leafMarkerPairs = AttachLeafMarkerBones(instance); // ②'a dev#1551 laneC2: "_end"等の重み無し末端マーカーをbones[]へ登録(LimbNode化)
            D2PDiagDump(instance, "05b after AttachLeafMarkerBones");
            BakeUniformScale(instance.transform, 1f);             // ②'' 階層スケール除去
            D2PDiagDump(instance, "06 after BakeUniformScale");
            D2PDiagShot(instance, outDir, "06_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            RebindToCurrent(instance);                            // ②''' bindposes再計算
            D2PDiagDump(instance, "07 after RebindToCurrent");
            D2PDiagShot(instance, outDir, "07_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            CollapseNestedArmatureContainers(instance);           // ②'''' wisker等ネストarmature対策(検証中)
            D2PDiagDump(instance, "08 after CollapseNestedArmatureContainers");
            D2PDiagShot(instance, outDir, "08_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            var skeletonRootDummy = InsertSkeletonRootDummy(instance); // ②''''' eRoot対策(Hipsの上にダミー)
            D2PDiagDump(instance, "09 after InsertSkeletonRootDummy");
            D2PDiagShot(instance, outDir, "09_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            RedirectRootBonesAwayFromSelf(instance, skeletonRootDummy); // ②'''''' eRoot対策(rootBone退避、汎用、dev#150で単一ダミーへ統一)
            D2PDiagDump(instance, "10 after RedirectRootBonesAwayFromSelf");
            D2PDiagShot(instance, outDir, "10_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            // dev#1356(揺れもの、dev#19サイドカー抽出): EnsureUniqueTransformNames()を
            // ここへ前倒しする(従来はStripNonEssentialPostBakeの後、ExportHumanoidの
            // 直前)。理由: ExtractPhysBoneChains()(次行)が書き出すボーン名は、
            // bones.json(ExportBones())と同じく「輸出される最終名」と一致させる
            // 必要がある。StripNonEssentialPostBakeはコンポーネントの除去のみで
            // Transformの追加・改名・削除を一切行わない(DestroyImmediate(c)は
            // Component、GameObjectではない)ため、この前倒しはEnsureUniqueTransformNames
            // が処理する名前集合を変えない(=dev#300の重複解消結果は不変、pak出力も不変)。
            // R1-3(work\rd_19_r1_wall\PROPOSAL.md「壁(a)Unity側1」)の順序リスク解消提案どおり。
            EnsureUniqueTransformNames(instance);                 // ④-b dev#300: 輸出直前に名前重複を解消(ExportHumanoid/ExportUnifiedFbx/ExportMaterials全ての手前が必須)
            // dev#1551 laneC2: leaf_marker_bones.jsonはbones.json/physbones.jsonと
            // 同じく「輸出される最終名」で書く必要があるため、EnsureUniqueTransformNames
            // の直後(名前確定後)に書く。
            WriteLeafMarkerBonesSidecar(outDir, leafMarkerPairs);
            // dev#1508 W1a: physbones.jsonの生成失敗で輸出全体を止めない(fail-open、
            // ただしログは必須)。File.WriteAllTextに到達する前に例外が起きた場合は
            // physbones.json自体が書かれないが、消費側(app_py\physbone_catalog.py
            // catalog_from_sidecar())は元々サイドカー不在をok=Falseの安全側
            // フォールバックとして扱う設計のため、ここで代替ファイルを書く必要はない。
            try
            {
                ExtractPhysBoneChains(instance, outDir);          // ③''''' dev#19(揺れもの)/dev#1356/dev#1508(W1a拡張): VRCPhysBoneはStripNonEssentialPostBakeで消える前提のため、消える直前に走査してサイドカーへ抽出する
            }
            catch (Exception e)
            {
                Debug.LogWarning("D2P: ExtractPhysBoneChains failed (" + e.GetType().Name + ": " + e.Message +
                    ") — physbones.json may be missing or incomplete; export continues (fail-open, dev#1508 W1a)");
            }
            StripNonEssentialPostBake(instance);                  // ④-a 第2段: 必須5型以外を除去(ExportHumanoidの直前)
            D2PDiagDump(instance, "11 after StripNonEssentialPostBake");
            D2PDiagShot(instance, outDir, "11_isolated", "front", new[] { "Beret", "Ribbon", "Body" });
            AssertNoNestedArmatureContainersRemain(instance);     // ④-c dev#876再調査: ネストされたarmatureコンテナの残留を輸出直前に名指しで止める(BlenderのKeyErrorのフォールバック)
            ExportHumanoid(instance, outDir);                     // ③ ベイク後実体から
            string fbxName = ExportUnifiedFbx(instance, outDir);  // ④ 統合FBX
            ExportMaterials(instance, outDir, fbxName);           // ⑤ 実テクスチャ
            ExportShapeKeys(instance, outDir, fbxName);           // ⑥ dev#1168: シェイプキー一覧(GUI用サイドカー)
            ExportBones(instance, outDir, fbxName);               // ⑦ dev#1277: 全ボーン名一覧(GUI用サイドカー)
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(instance);
        }
    }

    // dev#1551 laneC(揺れもの、服ボーンクリーンアップ): MA処理前(BakeNdmf直前)に、
    // 服armature(ModularAvatarMergeArmatureコンポーネントを持つTransform)配下の
    // 「自身にも子孫にも、いずれのSkinnedMeshRendererメッシュへの非ゼロウェイトも
    // 無い骨」をGameObjectごと削除する。
    //
    // 背景: Modular AvatarのMergeArmatureHookは、服armature側の非マッチ骨(例:
    // 素体と同名の耳骨鎖が服側にも残留しているケース)を、名前が一致する親骨
    // (素体・服で共有される骨)の子として再親化した上で`名前 + "$" + Guid`へ
    // マングルする(本ファイル内ExtractPhysBoneChains付近のコメント参照)。これが
    // 揺れ鎖(dev#1551条件2/3)を汚染する既知の赤の主因であり(#1551本文実測、
    // work\run_1551\gate\RESULT.md)、従来はPhysBone抽出時にignoreTransformsで
    // 枝刈りするだけの対症療法だった(BuildPhysBoneLeafChains)。本処理はMA実行前に
    // 汚染源そのものを消すことで根治する(オーナー裁定2026-08-17、
    // work\run_1551\PLAN.md)。
    //
    // 素体(マージ先)armatureの骨には一切触れない: ModularAvatarMergeArmature
    // コンポーネントは常に「マージされる側」(服armature)のルートに付き、
    // mergeTargetフィールドで素体側の対応骨を指す(Packages\nadena.dev.modular-avatar
    // \Runtime\ModularAvatarMergeArmature.cs実装で確認済み)。GetComponentsInChildren
    // で見つけたコンポーネント自身のtransform配下だけを走査するため、mergeTarget側
    // (素体)には構造的に触れない。
    //
    // 名前ではなくGetHierarchyPathをキーに使う理由: この呼び出し位置(BakeNdmfより
    // 前、EnsureUniqueTransformNamesよりずっと前)では、服armatureと素体armatureが
    // まだ別ツリーのまま存在しており、MergeArmatureが名前一致で対応付ける前提上、
    // 同名のTransformが両ツリーに重複して存在するのが通常である。名前をキーにすると
    // 服armature側の骨が素体側の同名骨のウェイトを誤って拾ってしまう恐れがあるため、
    // 常に一意なGetHierarchyPathを識別子として使う(BuildChildrenByNameMapが名前
    // キーで安全なのはEnsureUniqueTransformNames実行後だけ、という同関数のコメントの
    // 裏返し)。
    static void CleanupClothesBonesPreBake(GameObject root)
    {
        var mergeArmatureType = FindType("nadena.dev.modular_avatar.core.ModularAvatarMergeArmature");
        if (mergeArmatureType == null)
        {
            Debug.Log("D2P: [ClothesBoneCleanup] ModularAvatarMergeArmature type not found (Modular Avatar not installed); skipping");
            return;
        }
        var mergeComps = root.GetComponentsInChildren(mergeArmatureType, true);
        if (mergeComps.Length == 0)
        {
            Debug.Log("D2P: [ClothesBoneCleanup] no MergeArmature components found; nothing to clean up");
            return;
        }

        // 全SMRについて、実際にスキニングへ寄与するボーン(FlattenBlendMarkBoneUsed
        // と同じ判定、FlattenSkinnedMeshesの既存パターンを踏襲)とrootBone参照を
        // Transform参照で集計する(この段階では名前が重複しうるため、必ずTransform
        // の実体で集計してからGetHierarchyPathへ変換する)。ウェイトが不明な
        // メッシュ(classic BoneWeight形式と頂点数が一致しない)は、FlattenSkinnedMeshes
        // と同じ安全側フォールバック(全ボーンを使用扱い=削除対象にしない)を取る。
        var weightedTransforms = new HashSet<Transform>();
        var rootBoneTransforms = new HashSet<Transform>();
        foreach (var smr in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            if (smr.rootBone != null) rootBoneTransforms.Add(smr.rootBone);
            var mesh = smr.sharedMesh;
            var bones = smr.bones;
            if (mesh == null || bones == null || bones.Length == 0) continue;
            var vertexWeights = mesh.boneWeights;
            bool weightsAvailable = vertexWeights != null && vertexWeights.Length == mesh.vertexCount;
            if (!weightsAvailable)
            {
                // 判定不能: 疑わしきは削除しない(安全側)
                foreach (var b in bones)
                    if (b != null) weightedTransforms.Add(b);
                continue;
            }
            var boneUsed = new bool[bones.Length];
            for (int i = 0; i < vertexWeights.Length; i++)
            {
                var bw = vertexWeights[i];
                FlattenBlendMarkBoneUsed(boneUsed, bw.boneIndex0, bw.weight0);
                FlattenBlendMarkBoneUsed(boneUsed, bw.boneIndex1, bw.weight1);
                FlattenBlendMarkBoneUsed(boneUsed, bw.boneIndex2, bw.weight2);
                FlattenBlendMarkBoneUsed(boneUsed, bw.boneIndex3, bw.weight3);
            }
            for (int i = 0; i < bones.Length; i++)
                if (boneUsed[i] && bones[i] != null) weightedTransforms.Add(bones[i]);
        }

        int totalDeleted = 0;
        foreach (var mc in mergeComps)
        {
            var comp = mc as Component;
            if (comp == null) continue;  // 別のMergeArmature処理で既に削除済み(ネスト構成)
            Transform clothesRoot = comp.transform;
            if (clothesRoot == null) continue;

            var pathToTransform = new Dictionary<string, Transform>();
            var childrenByPath = new Dictionary<string, List<string>>();
            var stack = new Stack<Transform>();
            stack.Push(clothesRoot);
            while (stack.Count > 0)
            {
                var t = stack.Pop();
                string path = GetHierarchyPath(t);
                pathToTransform[path] = t;
                var kids = new List<string>();
                foreach (Transform c in t)
                {
                    kids.Add(GetHierarchyPath(c));
                    stack.Push(c);
                }
                childrenByPath[path] = kids;
            }

            var weightedKeys = new HashSet<string>();
            var rootBoneKeys = new HashSet<string>();
            foreach (var kv in pathToTransform)
            {
                if (weightedTransforms.Contains(kv.Value)) weightedKeys.Add(kv.Key);
                if (rootBoneTransforms.Contains(kv.Value)) rootBoneKeys.Add(kv.Key);
            }

            string rootKey = GetHierarchyPath(clothesRoot);
            var deletableKeys = FindDeletableClothesBoneKeys(rootKey, childrenByPath, weightedKeys, rootBoneKeys);

            foreach (var key in deletableKeys)
            {
                Transform t;
                if (!pathToTransform.TryGetValue(key, out t) || t == null) continue;
                string name = t.name;
                string path = GetHierarchyPath(t);
                try
                {
                    UnityEngine.Object.DestroyImmediate(t.gameObject);
                    totalDeleted++;
                    Debug.Log("D2P: [ClothesBoneCleanup] removed clothes bone: " + name + " @ " + path
                        + " (reason: no self/descendant SkinnedMeshRenderer weight, "
                        + "not referenced as any SkinnedMeshRenderer.rootBone)");
                }
                catch (Exception e)
                {
                    Debug.LogWarning("D2P: [ClothesBoneCleanup] removal failed: " + name + " @ " + path
                        + " (" + e.Message + ")");
                }
            }
        }
        Debug.Log("D2P: ClothesBoneCleanup complete, removed " + totalDeleted + " bone(s) under "
            + mergeComps.Length + " MergeArmature root(s) (pre-bake, weight-free clothes bone subtrees)");
    }

    // D2P_CLOTHESBONE_PURE_BEGIN
    // dev#1551 laneC: 服armature配下の骨のうち、自身にも子孫にもウェイトが無い骨を
    // 削除対象として判定する純粋関数。UnityEngine型に一切依存しない(文字列キーの
    // コレクションのみ)ため、dotnet単体で振る舞いを検証できる
    // (tests\unity_exporter\test_clothes_bone_cleanup_dev1551.py)。
    //
    // キーは名前ではなく呼び出し側が用意する一意な識別子(呼び出し側は
    // GetHierarchyPath等を渡す想定)。この関数自体はキーの意味を一切解釈しない。
    //
    // 判定規則(#1551 laneC BRIEF):
    //   1. clothesRootKey自身は削除対象にしない(MergeArmatureの合流点であり、
    //      削除すると以降のマージ自体が成立しなくなるため。安全側の実装判断)。
    //   2. rootBoneKeysに含まれる骨(いずれかのSkinnedMeshRendererのrootBoneとして
    //      参照されている骨)は、ウェイトの有無に関わらず削除しない(BRIEF記載の
    //      安全側条件)。
    //   3. 上記いずれにも該当しない骨のうち、自身にも子孫にもweightedKeysが
    //      1つも無いもの(ClothesBoneSubtreeHasWeightがfalse)を削除対象とする。
    //   4. 削除対象は「最上位のみ」を返す(GameObjectごと削除すれば子孫も自動的に
    //      消えるため、子孫を重複列挙しない。削除対象と判定した部分木の内部は
    //      それ以上再帰しない)。
    internal static bool ClothesBoneSubtreeHasWeight(
        string key, IDictionary<string, List<string>> childrenByKey, ISet<string> weightedKeys)
    {
        if (weightedKeys.Contains(key)) return true;
        List<string> children;
        if (!childrenByKey.TryGetValue(key, out children)) return false;
        foreach (var c in children)
            if (ClothesBoneSubtreeHasWeight(c, childrenByKey, weightedKeys)) return true;
        return false;
    }

    internal static List<string> FindDeletableClothesBoneKeys(
        string clothesRootKey, IDictionary<string, List<string>> childrenByKey,
        ISet<string> weightedKeys, ISet<string> rootBoneKeys)
    {
        var result = new List<string>();
        var stack = new Stack<KeyValuePair<string, bool>>();
        stack.Push(new KeyValuePair<string, bool>(clothesRootKey, true));
        while (stack.Count > 0)
        {
            var top = stack.Pop();
            string key = top.Key;
            bool isRoot = top.Value;
            bool protect = isRoot || rootBoneKeys.Contains(key)
                || ClothesBoneSubtreeHasWeight(key, childrenByKey, weightedKeys);
            if (!protect)
            {
                result.Add(key);
                continue;  // 部分木は丸ごと削除対象なのでこれ以上辿らない
            }
            List<string> children;
            if (childrenByKey.TryGetValue(key, out children))
                foreach (var c in children)
                    stack.Push(new KeyValuePair<string, bool>(c, false));
        }
        return result;
    }
    // D2P_CLOTHESBONE_PURE_END

    // ---- 一時診断(HZ班、位置バグ再調査用。原因特定後に削除する) ----
    static void D2PDiagDump(GameObject root, string label)
    {
        string[] names = { "Beret", "Ribbon", "SRB_AG1", "GameObject", "Head" };
        foreach (var n in names)
        {
            var matches = new List<Transform>();
            foreach (var t in root.GetComponentsInChildren<Transform>(true))
                if (t.name == n) matches.Add(t);
            if (matches.Count == 0)
            {
                Debug.Log($"D2PDIAG2[{label}] {n}: NOT FOUND (0 matches)");
                continue;
            }
            if (matches.Count > 1)
                Debug.Log($"D2PDIAG2[{label}] {n}: {matches.Count} MATCHES(!)");
            foreach (var found in matches)
            {
                var mabp = found.GetComponent("ModularAvatarBoneProxy");
                Debug.Log($"D2PDIAG2[{label}] {n} @ {GetHierarchyPath(found)}: "
                    + $"active={found.gameObject.activeInHierarchy} "
                    + $"parent={found.parent?.name} localPos={found.localPosition:F5} "
                    + $"localScale={found.localScale:F5} worldPos={found.position:F5} "
                    + $"lossyScale={found.lossyScale:F5} hasBoneProxy={mabp != null}");
            }
        }
    }
    // カメラで撮影しPNG保存(比較用、目視確認目的)。dir: "front"/"back"/"side"
    // isolateNames!=null なら、その名前のRendererだけ見せて他は隠す(位置の一意特定用)
    static void D2PDiagShot(GameObject root, string outDir, string name, string dir = "back",
                             string[] isolateNames = null)
    {
        var renderers = root.GetComponentsInChildren<Renderer>(false);
        if (renderers.Length == 0) { Debug.Log("D2PDIAG2SHOT: no renderers"); return; }
        var savedEnabled = new List<(Renderer, bool)>();
        if (isolateNames != null)
        {
            foreach (var r in renderers)
            {
                savedEnabled.Add((r, r.enabled));
                r.enabled = Array.IndexOf(isolateNames, r.gameObject.name) >= 0;
            }
        }
        Bounds b = default; bool has = false;
        foreach (var r in renderers)
        {
            if (!r.enabled) continue;
            if (!has) { b = r.bounds; has = true; } else b.Encapsulate(r.bounds);
        }
        if (!has) { Debug.Log("D2PDIAG2SHOT: no visible renderers for " + name); goto restore; }

        {
            var camGo = new GameObject("D2PDiagCam");
            var cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.6f, 0.6f, 0.6f, 1f);
            float dist = Mathf.Max(b.extents.magnitude * 2.2f, 1f);
            Vector3 offset = dir == "front" ? new Vector3(0, 0, dist)
                            : dir == "side" ? new Vector3(dist, 0, 0)
                            : new Vector3(0, 0, -dist);
            camGo.transform.position = b.center + offset;
            camGo.transform.LookAt(b.center, Vector3.up);
            cam.nearClipPlane = 0.01f;
            cam.farClipPlane = dist * 4f;

            int w = 512, h = 768;
            var rt = new RenderTexture(w, h, 24);
            cam.targetTexture = rt;
            cam.Render();
            var prevActive = RenderTexture.active;
            RenderTexture.active = rt;
            var tex = new Texture2D(w, h, TextureFormat.RGB24, false);
            tex.ReadPixels(new Rect(0, 0, w, h), 0, 0);
            tex.Apply();
            RenderTexture.active = prevActive;
            cam.targetTexture = null;
            rt.Release();

            var bytes = tex.EncodeToPNG();
            var path = Path.Combine(outDir, "d2pdiag_" + name + ".png");
            File.WriteAllBytes(path, bytes);
            Debug.Log("D2PDIAG2SHOT saved: " + path);

            UnityEngine.Object.DestroyImmediate(tex);
            UnityEngine.Object.DestroyImmediate(camGo);
        }
        restore:
        if (isolateNames != null)
            foreach (var (r, en) in savedEnabled) r.enabled = en;
    }
    // ---- 診断ここまで ----

    static Type FindType(string fullName)
    {
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            var t = asm.GetType(fullName);
            if (t != null) return t;
        }
        return null;
    }

    // 型がVRC公式(com.vrchat.*)/Modular Avatar/NDMF本体、または必須5型
    // (Transform/Animator/SkinnedMeshRenderer/MeshRenderer/MeshFilter)かどうかを
    // 判定する。名前空間のプレフィックス一致にすることで、SDK更新で型が増えても
    // 個別列挙なしに自動対応する。
    // 注意: Modular Avatarはパッケージ名がハイフン(nadena.dev.modular-avatar)だが
    // C#名前空間はアンダースコア(nadena.dev.modular_avatar)。ここを間違えると
    // MAコンポーネントを丸ごと消してベイクが壊れるため厳重に注意すること
    static bool IsWhitelistedComponentType(Type t)
    {
        if (t == typeof(Transform) || t == typeof(Animator)
            || t == typeof(SkinnedMeshRenderer) || t == typeof(MeshRenderer)
            || t == typeof(MeshFilter))
            return true;
        var ns = t.Namespace ?? "";
        return ns == "VRC" || ns.StartsWith("VRC.")
            || ns == "nadena.dev.modular_avatar" || ns.StartsWith("nadena.dev.modular_avatar.")
            || ns == "nadena.dev.ndmf" || ns.StartsWith("nadena.dev.ndmf.");
    }

    // D2P_HIERARCHY_PATH_BEGIN
    // ログ用: ルートからのHierarchyパス(Transform名を"/"で連結)
    static string GetHierarchyPath(Transform t)
    {
        var sb = new StringBuilder(t.name);
        for (var p = t.parent; p != null; p = p.parent)
            sb.Insert(0, p.name + "/");
        return sb.ToString();
    }
    // D2P_HIERARCHY_PATH_END

    // 第1段(ベイク前)ホワイトリスト。オーナー裁定「MA以外のNDMFプラグインは非対応」
    // を受け、VRC公式/Modular Avatar/NDMF本体/必須5型以外の**コンポーネントのみ**を
    // 全除去する(GameObjectそのものは消さない)。
    // 呼び出し位置は必ずBakeNdmfの"前"であること: NDMFのTransformingフェーズは
    // プラグインのマーカーコンポーネント(例: PoseClipperInstaller)をベイク実行時に
    // その場でスキャンするため(実データ確認済み)、BakeNdmfの後に置くと
    // 既にプラグインが実行済みになってしまい無効化の意味が無くなる。
    // 削除した型名+パスを1件ずつログに残す(取りこぼしの追跡・ユーザー問い合わせ対応用)
    static void StripNonWhitelistedPreBake(GameObject root)
    {
        int n = 0;
        foreach (var c in root.GetComponentsInChildren<Component>(true))
        {
            if (c == null) continue;  // missing script等
            var t = c.GetType();
            if (IsWhitelistedComponentType(t)) continue;
            string typeName = t.FullName;
            string path = GetHierarchyPath(c.transform);
            try
            {
                UnityEngine.Object.DestroyImmediate(c);
                n++;
                Debug.Log("D2P: [PreBakeSanitize] removed: " + typeName + " @ " + path);
            }
            catch (Exception e)
            {
                Debug.LogWarning("D2P: [PreBakeSanitize] removal failed: " + typeName + " @ " + path
                                  + " (" + e.Message + ")");
            }
        }
        Debug.Log("D2P: PreBakeSanitize complete, removed " + n + " component(s)"
                   + " (targets everything except VRC official/ModularAvatar/NDMF core+"
                   + "Transform/Animator/SkinnedMeshRenderer/MeshRenderer/MeshFilter)");
    }

    // D2P_COLLAPSE455_ESSENTIAL_BEGIN
    // FBX輸出とhumanoid.json生成に真に必要な5型(Transform/Animator/
    // SkinnedMeshRenderer/MeshRenderer/MeshFilter)かどうかの判定。
    // StripNonEssentialPostBake(除去)とCollapseNestedArmatureContainers
    // (収縮可否判定)の両方がこの1箇所を参照する(dev#455: 二重定義していた
    // ことで、収縮判定側だけ古い「Transform以外禁止」基準のまま取り残され、
    // Merge Armatureが生成するPhysBone付きアンカーノードがcollapse対象から
    // 漏れてFBXに残存し、BlenderのFBXインポータでKeyErrorになっていた)。
    static bool IsEssentialComponentType(Type t)
    {
        return t == typeof(Transform) || t == typeof(Animator)
            || t == typeof(SkinnedMeshRenderer) || t == typeof(MeshRenderer)
            || t == typeof(MeshFilter);
    }

    // dev#876: 上のIsEssentialComponentTypeは「型」だけでAnimatorを無条件に
    // 必須扱いする。しかしVRCアバター規約上、正当なAnimatorは輸出ルート
    // (VRCAvatarDescriptorと同じGameObject)に必ず1つだけ存在するはずであり、
    // それ以外の場所にあるAnimatorは、Merge Armature等で合流した衣装/
    // アクセサリー資産(自前のFBXをUnityへ取り込んだ際の残骸)が持ち込んだ
    // だけの、実データを保持しない使い捨てコンポーネントである。
    // 実例(dev#876、V72HEU9N msg#208/8F7K2UGK): Head(本体ボーン)の直下に
    // "Armature"という名の非ボーンコンテナがネストされ、その下に第2の
    // "Hips"(ボーン)が存在する構造で、このコンテナ自身が残置Animatorを
    // 持っていたため、CollapseNestedArmatureContainersが「Animatorがあるから
    // 必須」と誤判定して収縮対象から漏れ、FBXへ生残ってBlenderの
    // find_armatures()に発見されず、mesh.armature_setup[d2p_skeleton_root]が
    // 未登録のままKeyErrorになっていた(dev#455が修正した「どうせ後で消える
    // コンポーネントを理由に収縮を諦めない」という趣旨を、Animatorという
    // 型そのものにも一般化する)。
    // 輸出ルート自身のAnimatorだけをインスタンス単位で特定し、それ以外の
    // Animatorは必須扱いしない。
    static Component FindPrimaryAnimator(GameObject root)
    {
        foreach (var c in root.transform.GetComponents<Component>())
            if (c != null && c.GetType() == typeof(Animator)) return c;
        return null;
    }

    // コンポーネント1つが「実データを保持する必須型」かどうかを判定する。
    // Animator以外はIsEssentialComponentTypeと同じ(型だけで判定)。Animatorは
    // primaryAnimator(輸出ルート自身のAnimator)と同一インスタンスの場合のみ
    // 必須とする。
    static bool IsEssentialComponent(Component c, Component primaryAnimator)
    {
        var t = c.GetType();
        if (t == typeof(Animator)) return c == primaryAnimator;
        return IsEssentialComponentType(t);
    }

    // 対象Transformが、Transform以外の「実データを保持する」必須型
    // (輸出ルート自身のAnimator/SkinnedMeshRenderer/MeshRenderer/MeshFilter)を
    // 1つでも持っているかどうか。GameObjectごと破棄する収縮(Collapse)では、
    // こうしたデータ保持コンポーネントを道連れに失ってはならない。
    // 一方、それ以外の型(VRCPhysBone/Collider/Constraint等、および輸出
    // ルート以外に残置されたAnimator)は、StripNonEssentialPostBakeでどうせ
    // 後から除去される「使い捨て」コンポーネントなので、これを理由に収縮を
    // 諦める必要はない(dev#455の修正趣旨: 「どうせ後で消えるコンポーネント」
    // を理由に収縮を諦めない。dev#876でAnimatorにも一般化)。
    static bool HasEssentialNonTransformComponent(Transform t, Component primaryAnimator)
    {
        foreach (var c in t.GetComponents<Component>())
        {
            if (c == null) continue;  // missing script等は道連れにしてよい(実データではない)
            if (c.GetType() == typeof(Transform)) continue;
            if (IsEssentialComponent(c, primaryAnimator)) return true;
        }
        return false;
    }
    // D2P_COLLAPSE455_ESSENTIAL_END

    // 第2段(ベイク後)ホワイトリスト。ベイク・各種ボーン処理が全て終わった後、
    // FBX輸出とhumanoid.json生成に必要な5型(Transform/Animator/
    // SkinnedMeshRenderer/MeshRenderer/MeshFilter)以外のコンポーネントを
    // 全除去する(GameObjectそのものは消さない)。
    // 呼び出し位置は必ずExportHumanoidの"前"であること。
    // 既存StripConstraints(IConstraint一括除去)とは独立で重複除去になるが、
    // 既存の安定した処理を壊さないため両方残す(実害なし)。
    // 削除した型名+パスを1件ずつログに残す
    static void StripNonEssentialPostBake(GameObject root)
    {
        int n = 0;
        var primaryAnimator = FindPrimaryAnimator(root);  // dev#876: 輸出ルート以外の残置Animatorは使い捨て扱いにする
        foreach (var c in root.GetComponentsInChildren<Component>(true))
        {
            if (c == null) continue;
            var t = c.GetType();
            if (IsEssentialComponent(c, primaryAnimator))
                continue;
            string typeName = t.FullName;
            string path = GetHierarchyPath(c.transform);
            try
            {
                UnityEngine.Object.DestroyImmediate(c);
                n++;
                Debug.Log("D2P: [PostBakeSanitize] removed: " + typeName + " @ " + path);
            }
            catch (Exception e)
            {
                Debug.LogWarning("D2P: [PostBakeSanitize] removal failed: " + typeName + " @ " + path
                                  + " (" + e.Message + ")");
            }
        }
        Debug.Log("D2P: PostBakeSanitize complete, removed " + n + " component(s)"
                   + " (keeps only Transform/Animator/SkinnedMeshRenderer/MeshRenderer/MeshFilter)");
    }

    // dev#194(実報告SE48AGFP): 同居NDMFプラグイン(実例: Light Limit Changer/
    // io.github.azukimochi.Utils)のアセンブリ静的初期化子(static constructor)が
    // 一度失敗すると、.NETは同一AppDomain内でその型への以後のアクセスを全て
    // 即座に TypeInitializationException で返す(BeforeFieldInit失敗のキャッシュ、
    // プロセス/Editorセッションが終わるまで解除されない)。reflection経由の
    // MethodInfo.Invokeはこれを更に TargetInvocationException で包んで返すため、
    // 生の"Exception has been thrown by the target of an invocation."だけでは
    // 原因のパッケージ・型がまったく特定できず、ユーザーもDiveToPalworld側も
    // 対処できない。
    // ここでは特定パッケージ名をコードに一切書かず(サードパーティ製アセットに
    // 特別対応しない裁定と同じ「入口で正規化、特別扱いを積まない」原則)、
    // 例外チェーンを実際に辿って
    // 壊れた型の名前を抽出し、"どの第三者パッケージが原因でも通用する"汎用の
    // 診断メッセージへ変換する。型初期化失敗はAppDomain内で恒久的(Editor再起動
    // までは同じ失敗を必ず再発する)なので、ここで自動リトライ/フォールバック
    // 経路を試みても同じ壊れた型に触れば再度失敗するだけであり、成功したかの
    // ように振る舞うことは「効いていないのに直った」を偽装する害の方が大きい。
    // よって選んだ方針は「輸出を止めるが、原因と対処が一目でわかる1行に変換する」。
    // Unity非依存の純粋関数として実装し、Unity無しの環境からも本番コードその
    // ものを抽出してdotnetでコンパイル・実行できるようにする
    // (tests\unity_exporter\test_thirdparty_init_guard.py)。
    // D2P_INITGUARD_PURE_BEGIN
    internal static string FindBrokenTypeInitializerName(Exception e)
    {
        for (var cur = e; cur != null; cur = cur.InnerException)
        {
            var tie = cur as TypeInitializationException;
            if (tie != null) return tie.TypeName;
        }
        return null;
    }

    internal static Exception RootCause(Exception e)
    {
        var cur = e;
        while (cur.InnerException != null) cur = cur.InnerException;
        return cur;
    }

    internal static string BuildInvocationFailureMessage(string stepName, Exception e)
    {
        string brokenType = FindBrokenTypeInitializerName(e);
        if (brokenType != null)
        {
            return stepName + ": static initialization of third-party type '" + brokenType +
                "' failed, and this same failure will recur for the rest of this Unity Editor " +
                "session (the .NET runtime caches type-initialization failures until the process " +
                "ends). Fix: 1) restart the Unity Editor, or 2) temporarily disable/remove the " +
                "offending package (check Package Manager), then re-export.";
        }
        var root = RootCause(e);
        return stepName + " failed: " + root.GetType().Name + ": " + root.Message;
    }
    // D2P_INITGUARD_PURE_END

    // NDMF(Modular Avatar等の非破壊改変基盤)のベイクを実体へ適用する。
    // パッケージ参照を増やさないためreflectionで呼ぶ。未導入ならスキップ
    static void BakeNdmf(GameObject root)
    {
        var t = FindType("nadena.dev.ndmf.AvatarProcessor");
        if (t == null)
        {
            Debug.Log("D2P: NDMF not installed; skipping bake");
            return;
        }
        var mi = t.GetMethod("ProcessAvatar",
            BindingFlags.Public | BindingFlags.Static,
            null, new[] { typeof(GameObject) }, null);
        if (mi == null)
            throw new Exception("AvatarProcessor.ProcessAvatar not found (incompatible NDMF version)");
        try
        {
            mi.Invoke(null, new object[] { root });
        }
        catch (TargetInvocationException tie)
        {
            // NDMF本体は通常このtry内で個々のプラグインの失敗を握りつぶすため、ここに
            // 来るのは想定外(NDMFの将来バージョンでの挙動変化等)の防御的対応。
            Debug.LogException(tie);
            throw new Exception(BuildInvocationFailureMessage("NDMF bake", tie));
        }
        Debug.Log("D2P: NDMF bake complete");
    }

    // dev#1551(postma-snapshot、二層オラクル定式のA2サイドカー): BakeNdmf直後
    // (MA/NDMF処理完了直後、FBX輸出やその後の破壊的処理
    // [StripInactive/ConvertStaticMeshesToSkinned/FlattenSkinnedMeshes/
    // BakeUniformScale/RebindToCurrent/CollapseNestedArmatureContainers/
    // InsertSkeletonRootDummy/RedirectRootBonesAwayFromSelf/
    // EnsureUniqueTransformNames]より前)のUnityヒエラルキーを、座標・回転・
    // ウェイトの生スナップショットとしてサイドカーへ出す。
    //
    // dev#1551コメント(2026-08-17、オーナー裁定「受入基準の運用明確化」)が
    // 定めた二層オラクルの座標・回転・ウェイト側:「MA(NDMF)処理直後のUnity
    // ヒエラルキー(VRCビルド相当)を左辺(オラクル)とし、以降の全段(輸出FBX→
    // step01→…→pak)を厳密1:1(float誤差のみ)で判定する」。これが無いと
    // 「素体との差がMAの正常動作かバグか」を帰属できない(既知の未解決:
    // work\run_1551\laneC2\NOTES.md「残る赤③」の0.2〜0.6mm系統的座標残差、
    // work\run_1551\acceptance\weightcheck_comodo_p4s2.md の揺れ鎖ウェイトFAIL)。
    //
    // 座標系: Unityのワールド座標をそのまま出す(左手系, Y-up, メートル,
    // 軸/単位変換は一切行わない)。Blender側(extract_bones.py/
    // extract_vertices.pyが読むFBXラウンドトリップ後の右手系Z-up空間)への
    // 変換は本Exporterの責務ではなく、消費側アダプタ(work\run_1551\laneC3_gate\)
    // が担う——このExporterはUnityの生の値を偽らず出すことに徹する。
    //
    // tail_world: Unityのボーン(Transform)にはBlenderのEditBoneのような
    // head/tail概念が無いため、「直接の子が1件のみなら、その子のworld位置」を
    // 疑似tailとして採用する(Blenderの葉ボーンtail推定ヒューリスティックが
    // 単一子ケースで実際に正しく解決するのと同じ実測、work\run_1551\laneC2\NOTES.md)。
    // 0件は末端(head=tailを出しleaf_no_child)、2件以上は最初の子(sibling順)を
    // 採用しmulti_child_firstを記録する(どちらも実測値をそのまま出す。
    // tail定義の限界を隠さず消費側で解釈できるようchild_count/tail_sourceを併記)。
    //
    // 失敗時: 本機能は検証専用の追加サイドカーであり、失敗しても輸出全体を
    // 止めない(fail-open、physbones.json/ExtractPhysBoneChainsと同じ方針)。
    // 呼び出し側(Export())でtry/catchする。
    static void WriteA2Snapshot(GameObject root, string outDir)
    {
        var CI = System.Globalization.CultureInfo.InvariantCulture;
        var humanNames = new HashSet<string>();
        try
        {
            var animator = SelectHumanoidAnimator(root);
            if (animator != null && animator.avatar != null && animator.avatar.isHuman)
            {
                foreach (var hb in animator.avatar.humanDescription.human)
                    if (!string.IsNullOrEmpty(hb.boneName)) humanNames.Add(hb.boneName);
            }
        }
        catch (Exception e)
        {
            Debug.LogWarning("D2P: WriteA2Snapshot: humanoid bone name detection failed ("
                + e.GetType().Name + ": " + e.Message + "); is_humanoid will be false for all bones");
        }

        var all = new List<Transform>();
        CollectAllTransforms(root.transform, all);

        // --- vertices (先に集計してweight totalsをbones側へ流用する) ---
        var smrs = root.GetComponentsInChildren<SkinnedMeshRenderer>(true);
        var weightTotals = new Dictionary<string, Dictionary<string, double>>();  // bone -> mesh -> total
        var meshNames = new List<string>();
        var verticesSb = new StringBuilder();
        verticesSb.Append("{\n  \"format\": \"divetopalworld-a2vertices-1\",\n");
        verticesSb.Append("  \"coordinate_system\": \"unity_world_lh_yup_meters\",\n");
        verticesSb.AppendFormat("  \"source\": \"{0}\",\n", J(root.name));
        verticesSb.AppendFormat("  \"armature\": \"{0}\",\n", J(root.name));
        verticesSb.Append("  \"multi_armature_warning\": null,\n");
        verticesSb.Append("  \"vertices\": [\n");
        bool firstVert = true;
        long vertCount = 0;

        foreach (var smr in smrs)
        {
            if (smr.sharedMesh == null || smr.bones == null || smr.bones.Length == 0) continue;
            var mesh = smr.sharedMesh;
            var bindposes = mesh.bindposes;
            if (bindposes == null || bindposes.Length == 0) continue;
            meshNames.Add(smr.name);

            int boneCount = bindposes.Length;
            var boneMats = new Matrix4x4[boneCount];
            var boneNames = new string[boneCount];
            for (int b = 0; b < boneCount; b++)
            {
                if (b < smr.bones.Length && smr.bones[b] != null)
                {
                    boneMats[b] = smr.bones[b].localToWorldMatrix * bindposes[b];
                    boneNames[b] = smr.bones[b].name;
                }
                else
                {
                    boneMats[b] = Matrix4x4.identity;
                    boneNames[b] = null;
                }
            }

            var verts = mesh.vertices;
            var boneWeights = mesh.boneWeights;
            bool weightsAvailable = boneWeights != null && boneWeights.Length == verts.Length;

            for (int vi = 0; vi < verts.Length; vi++)
            {
                Vector3 worldPos;
                var perVertWeights = new List<KeyValuePair<string, float>>();
                if (weightsAvailable)
                {
                    var bw = boneWeights[vi];
                    worldPos = Vector3.zero;
                    A2AccumulateVertex(ref worldPos, boneMats, bw.boneIndex0, bw.weight0, verts[vi]);
                    A2AccumulateVertex(ref worldPos, boneMats, bw.boneIndex1, bw.weight1, verts[vi]);
                    A2AccumulateVertex(ref worldPos, boneMats, bw.boneIndex2, bw.weight2, verts[vi]);
                    A2AccumulateVertex(ref worldPos, boneMats, bw.boneIndex3, bw.weight3, verts[vi]);
                    A2AddWeight(perVertWeights, boneNames, bw.boneIndex0, bw.weight0);
                    A2AddWeight(perVertWeights, boneNames, bw.boneIndex1, bw.weight1);
                    A2AddWeight(perVertWeights, boneNames, bw.boneIndex2, bw.weight2);
                    A2AddWeight(perVertWeights, boneNames, bw.boneIndex3, bw.weight3);
                }
                else
                {
                    // ウェイト無し(rigid): bones[0]の行列のみ適用
                    // (FlattenSkinnedMeshesの同種フォールバックと同じ規約)
                    worldPos = boneMats[0].MultiplyPoint3x4(verts[vi]);
                }

                if (!firstVert) verticesSb.Append(",\n");
                firstVert = false;
                verticesSb.AppendFormat(CI,
                    "    {{\"mesh\": \"{0}\", \"vindex\": {1}, \"pos_world\": [{2}, {3}, {4}], \"weights\": {{",
                    J(smr.name), vi, worldPos.x, worldPos.y, worldPos.z);
                bool firstW = true;
                foreach (var kv in perVertWeights)
                {
                    if (kv.Key == null || kv.Value <= 0f) continue;
                    if (!firstW) verticesSb.Append(", ");
                    firstW = false;
                    verticesSb.AppendFormat(CI, "\"{0}\": {1}", J(kv.Key), kv.Value);
                    if (!weightTotals.TryGetValue(kv.Key, out var meshTotals))
                    {
                        meshTotals = new Dictionary<string, double>();
                        weightTotals[kv.Key] = meshTotals;
                    }
                    meshTotals[smr.name] = (meshTotals.TryGetValue(smr.name, out var cur) ? cur : 0.0) + kv.Value;
                }
                verticesSb.Append("}}");
                vertCount++;
            }
        }
        verticesSb.Append("\n  ],\n");
        verticesSb.AppendFormat("  \"vertex_count\": {0},\n", vertCount);
        verticesSb.Append("  \"mesh_names\": [");
        for (int i = 0; i < meshNames.Count; i++)
        {
            if (i > 0) verticesSb.Append(", ");
            verticesSb.AppendFormat("\"{0}\"", J(meshNames[i]));
        }
        verticesSb.Append("],\n  \"meshes_with_shape_keys\": []\n}\n");

        // --- bones ---
        var bonesSb = new StringBuilder();
        bonesSb.Append("{\n  \"format\": \"divetopalworld-a2bones-1\",\n");
        bonesSb.Append("  \"coordinate_system\": \"unity_world_lh_yup_meters\",\n");
        bonesSb.AppendFormat("  \"source\": \"{0}\",\n", J(root.name));
        bonesSb.AppendFormat("  \"armature\": \"{0}\",\n", J(root.name));
        bonesSb.AppendFormat("  \"bone_count\": {0},\n", Math.Max(0, all.Count - 1));
        bonesSb.Append("  \"multi_armature_warning\": null,\n");
        bonesSb.Append("  \"bones\": {\n");
        bool firstBone = true;
        foreach (var t in all)
        {
            if (t == root.transform) continue;  // rootそのものは骨として扱わない(extract_bones.pyのarmatureオブジェクト自身を含めない慣行と一致)
            string parentName = (t.parent == null || t.parent == root.transform) ? null : t.parent.name;
            Vector3 head = t.position;
            Vector3 tail;
            string tailSource;
            int childCount = t.childCount;
            if (childCount == 0) { tail = head; tailSource = "leaf_no_child"; }
            else if (childCount == 1) { tail = t.GetChild(0).position; tailSource = "single_child"; }
            else { tail = t.GetChild(0).position; tailSource = "multi_child_first"; }
            var q = t.rotation;
            float length = (tail - head).magnitude;
            bool isHuman = humanNames.Contains(t.name);

            if (!firstBone) bonesSb.Append(",\n");
            firstBone = false;
            bonesSb.AppendFormat(CI,
                "    \"{0}\": {{\"parent\": {1}, \"head_world\": [{2}, {3}, {4}], " +
                "\"tail_world\": [{5}, {6}, {7}], \"length\": {8}, " +
                "\"quat_world\": [{9}, {10}, {11}, {12}], \"is_humanoid\": {13}, " +
                "\"child_count\": {14}, \"tail_source\": \"{15}\"}}",
                J(t.name),
                parentName == null ? "null" : "\"" + J(parentName) + "\"",
                head.x, head.y, head.z,
                tail.x, tail.y, tail.z,
                length,
                q.w, q.x, q.y, q.z,
                isHuman ? "true" : "false",
                childCount, tailSource);
        }
        bonesSb.Append("\n  },\n");
        bonesSb.Append("  \"mesh_names\": [");
        for (int i = 0; i < meshNames.Count; i++)
        {
            if (i > 0) bonesSb.Append(", ");
            bonesSb.AppendFormat("\"{0}\"", J(meshNames[i]));
        }
        bonesSb.Append("],\n");
        bonesSb.Append("  \"weights\": {\n");
        bool firstW2 = true;
        foreach (var kv in weightTotals)
        {
            if (!firstW2) bonesSb.Append(",\n");
            firstW2 = false;
            double total = 0.0;
            foreach (var mv in kv.Value.Values) total += mv;
            bonesSb.AppendFormat(CI, "    \"{0}\": {{\"total\": {1}, \"meshes\": {{", J(kv.Key), total);
            bool firstM = true;
            foreach (var mv in kv.Value)
            {
                if (!firstM) bonesSb.Append(", ");
                firstM = false;
                bonesSb.AppendFormat(CI, "\"{0}\": {1}", J(mv.Key), mv.Value);
            }
            bonesSb.Append("}}");
        }
        bonesSb.Append("\n  }\n}\n");

        File.WriteAllText(Path.Combine(outDir, "a2_bones.json"), bonesSb.ToString(), new UTF8Encoding(false));
        File.WriteAllText(Path.Combine(outDir, "a2_vertices.json"), verticesSb.ToString(), new UTF8Encoding(false));
        Debug.Log("D2P: WriteA2Snapshot wrote a2_bones.json (" + Math.Max(0, all.Count - 1)
            + " transforms) and a2_vertices.json (" + vertCount + " vertices, " + meshNames.Count + " meshes)");
    }

    // D2P_A2HELPERS_BEGIN
    static void A2AccumulateVertex(ref Vector3 acc, Matrix4x4[] boneMats, int boneIndex, float weight, Vector3 localVert)
    {
        if (weight <= 0f) return;
        if (boneIndex < 0 || boneIndex >= boneMats.Length) return;
        acc += boneMats[boneIndex].MultiplyPoint3x4(localVert) * weight;
    }

    static void A2AddWeight(List<KeyValuePair<string, float>> list, string[] boneNames, int boneIndex, float weight)
    {
        if (weight <= 0f) return;
        if (boneIndex < 0 || boneIndex >= boneNames.Length) return;
        var name = boneNames[boneIndex];
        if (name == null) return;
        list.Add(new KeyValuePair<string, float>(name, weight));
    }
    // D2P_A2HELPERS_END

    // Unity公式FBX Exporter(com.unity.formats.fbx@4.2.1)の
    // ModelExporter.ExportConstraints は特定の構成(2026-07-26実測: FaceEmo等
    // MA以外のNDMFプラグインが同居するsha-ta検体)で例外を投げ、輸出全体が失敗する。
    // Unityの制約コンポーネント(ParentConstraint/PositionConstraint/RotationConstraint/
    // ScaleConstraint/AimConstraint/LookAtConstraint、すべてIConstraint実装)は
    // 「Is Activeな間、毎フレーム計算結果を自身のTransformのローカル値へ直接
    // 上書きする」方式であり、コンポーネント自体は最終姿勢とは別の独立した
    // ポーズ情報を保持しない。つまりprefab保存時点でIs Activeなら、その時点の
    // Transformのローカル値は既に制約適用後の姿勢そのものであり、以降このメソッド内で
    // コンポーネントを消してもTransformの値自体はそのまま(このメソッドは
    // Transformの値を書き換えない)。この呼び出しはBakeNdmf直後・
    // FlattenSkinnedMeshes/BakeUniformScale/RebindToCurrent(いずれもボーンの
    // "現在の"ワールド行列を読むだけで、コンポーネントの有無を見ない)より前に
    // 置いているが、後続処理はTransformの現在値のみを参照するため順序に依存しない。
    // 除去は輸出用の一時複製(instance)に対してのみ行う——StripInactive等と同じ流儀
    static void StripConstraints(GameObject root)
    {
        D2PConstraintDiag.LogBoneConstraints(root);  // dev#1174: 除去前にどのボーンへ何が付いていたかを記録(ロジック本体はD2PConstraintDiag.cs、並行レーンdev#518との衝突回避)
        int n = 0;
        foreach (var c in root.GetComponentsInChildren<UnityEngine.Animations.IConstraint>(true))
        {
            var comp = c as Component;
            if (comp == null) continue;
            UnityEngine.Object.DestroyImmediate(comp);
            n++;
        }
        if (n > 0)
            Debug.Log("D2P: removed " + n + " Constraint component(s) (Transform values unchanged, export-only duplicate)");
    }

    // シーンに置いた時点で見えていない物(inactiveオブジェクト・無効レンダラー)を
    // 実体から除去する。ただしactiveなスキンメッシュが参照するボーンの階層は残す
    static void StripInactive(GameObject root)
    {
        var needed = new HashSet<Transform>();
        foreach (var r in root.GetComponentsInChildren<SkinnedMeshRenderer>(false))
        {
            if (!r.enabled) continue;
            foreach (var b in r.bones)
                for (var t = b; t != null; t = t.parent) needed.Add(t);
            for (var t = r.rootBone; t != null; t = t.parent) needed.Add(t);
        }
        StripWalk(root.transform, needed);
    }

    static void StripWalk(Transform t, HashSet<Transform> needed)
    {
        var children = new List<Transform>();
        foreach (Transform c in t) children.Add(c);
        foreach (var c in children)
        {
            if (!c.gameObject.activeSelf)
            {
                if (ContainsAny(c, needed))
                {
                    // ボーンとして必要なので階層は残し、見た目だけ除去
                    foreach (var r in c.GetComponentsInChildren<Renderer>(true))
                        UnityEngine.Object.DestroyImmediate(r);
                    foreach (var mf in c.GetComponentsInChildren<MeshFilter>(true))
                        UnityEngine.Object.DestroyImmediate(mf);
                }
                else
                {
                    UnityEngine.Object.DestroyImmediate(c.gameObject);
                }
                continue;
            }
            var rend = c.GetComponent<Renderer>();
            if (rend != null && !rend.enabled)
            {
                UnityEngine.Object.DestroyImmediate(rend);
                var mf2 = c.GetComponent<MeshFilter>();
                if (mf2 != null) UnityEngine.Object.DestroyImmediate(mf2);
            }
            StripWalk(c, needed);
        }
    }

    static bool ContainsAny(Transform t, HashSet<Transform> set)
    {
        if (set.Contains(t)) return true;
        foreach (Transform c in t)
            if (ContainsAny(c, set)) return true;
        return false;
    }

    // スケール正規化後のボーンワールドで全SMRのbindposesを取り直す
    // (FlattenSkinnedMeshes→BakeUniformScaleの後に呼ぶ。メッシュ頂点は
    //  ワールド座標・ノードは恒等なので bindpose = worldToLocal で整合する)
    static void RebindToCurrent(GameObject root)
    {
        foreach (var r in root.GetComponentsInChildren<SkinnedMeshRenderer>(false))
        {
            if (r.sharedMesh == null || r.bones == null || r.bones.Length == 0)
                continue;
            var bp = new Matrix4x4[r.bones.Length];
            for (int b = 0; b < r.bones.Length; b++)
                bp[b] = r.bones[b] != null
                    ? r.bones[b].worldToLocalMatrix : Matrix4x4.identity;
            r.sharedMesh.bindposes = bp;
        }
    }

    // 階層の一様スケール(VRChatリグのArmature=0.458等)をボーン位置へ焼き込み、
    // 全ノードをscale=1にする。ワールド位置は不変。回転は一様スケールなら不変。
    // 非一様スケールは対象外(警告のみ)
    static void BakeUniformScale(Transform t, float acc)
    {
        var ls = t.localScale;
        float s = (ls.x + ls.y + ls.z) / 3f;
        if (Mathf.Abs(ls.x - ls.y) > 1e-4f * Mathf.Abs(s)
            || Mathf.Abs(ls.x - ls.z) > 1e-4f * Mathf.Abs(s))
        {
            Debug.LogWarning("D2P: cannot normalize non-uniform scale: " + t.name
                             + " " + ls);
            return;  // この枝はそのまま(以降の子も触らない)
        }
        t.localPosition = t.localPosition * acc;
        float acc2 = acc * s;
        t.localScale = Vector3.one;

        // 非スキンメッシュ(MeshFilter直付け、帽子・リボン等のBone Proxyアクセサリ)対策
        // (2026-07-26実測、shapell_Osaki帽子/リボン位置バグの根本原因):
        // このメソッドは「ノード原点のワールド位置」を保つよう親のスケールを
        // 子のlocalPositionへ焼き込むが、メッシュ自身の頂点データ(原点から離れた
        // 位置にあることが多い。今回のケースでは累積1.43倍)へは何もしない。
        // SkinnedMeshRendererはFlattenSkinnedMeshes()で既にルート直下・恒等姿勢
        // (acc=1)へ変換済みなのでこの分岐に来ないが、非スキンのMeshFilterは
        // 素通りしてここへ来る。ノードのlocalScaleを1へ強制する代わりに、
        // 除去する分の累積スケール(acc2)をメッシュの頂点自体へ焼き込むことで、
        // 「ノード原点は同じ位置・頂点の実寸も同じ見た目」を両立する
        // (Unity上のRenderer.boundsで正しく見えている実際の見た目を、
        // スケール除去後も再現する)。
        var mf = t.GetComponent<MeshFilter>();
        if (mf != null && mf.sharedMesh != null && Mathf.Abs(acc2 - 1f) > 1e-6f)
        {
            var mesh = UnityEngine.Object.Instantiate(mf.sharedMesh);
            mesh.name = mf.sharedMesh.name;
            var verts = mesh.vertices;
            for (int i = 0; i < verts.Length; i++) verts[i] *= acc2;
            mesh.vertices = verts;
            mesh.RecalculateBounds();
            mf.sharedMesh = mesh;
            Debug.Log("D2P: BakeUniformScale: baked cumulative scale "
                       + acc2.ToString("F4") + " into vertices of non-skinned mesh: " + GetHierarchyPath(t));
        }

        foreach (Transform c in t)
            BakeUniformScale(c, acc2);
    }

    // 非スキンメッシュ(MeshFilter+MeshRenderer。帽子・リボン等、ボーンへ
    // Transform直付けする一般的なVRChatアクセサリ構成)を、その所属ボーンへ
    // 100%ウェイトのSkinnedMeshRendererへ変換する。
    // 狙い: 以降の全工程(FlattenSkinnedMeshes/BakeUniformScaleの頂点焼き込み/
    // chibi-fit/RebindToCurrent等)はSkinnedMeshRendererを前提に動くため、
    // 非スキンメッシュだけがそこから取り残され、体だけ変形して装飾品が
    // 置いていかれる(2026-07-26実測、shapell_Osakiのベレー帽・リボン)。
    // ここで一律SkinnedMeshRenderer化しておけば、後続処理が全メッシュへ
    // 一様に効く。
    // 所属ボーンはTransformの親をたどって特定する(NDMFベイク・
    // StripInactive後の階層は、アクセサリがボーンへ直接ぶら下がる構成に
    // なっている——Unity側は階層がそのままボーン構造を持つ)。
    // 親が無い(ルート直下)等で所属ボーンが特定できない場合は変換せず
    // そのまま残し、警告のみ出す(以降はBakeUniformScaleの頂点焼き込み
    // フォールバックに任せる)。
    // sharedMeshは複製してから加工し、元アセットには触らない。
    // 呼び出し位置はBakeNdmf後・FlattenSkinnedMeshes前が必須:
    // FlattenSkinnedMeshes以降の全処理はSkinnedMeshRendererのみを走査するため、
    // 変換はそれより前でなければ意味が無い。StripInactiveの後に置くことで、
    // 実際に書き出されるメッシュだけを変換対象へ絞れる。
    // 元からSkinnedMeshRendererのものには触らない
    // (SkinnedMeshRendererはMeshRendererを継承しないため、
    //  GetComponentsInChildren<MeshRenderer>では列挙されず自然に対象外になる)。
    static void ConvertStaticMeshesToSkinned(GameObject root)
    {
        // 変換中にコンポーネント構成を変えるため、対象を先に列挙してから処理する
        var targets = new List<MeshRenderer>(root.GetComponentsInChildren<MeshRenderer>(false));
        int n = 0, skipped = 0;
        foreach (var mr in targets)
        {
            var t = mr.transform;
            var mf = t.GetComponent<MeshFilter>();
            if (mf == null || mf.sharedMesh == null) continue;

            var bone = t.parent;
            if (bone == null)
            {
                Debug.LogWarning("D2P: [Unskin] cannot determine owning bone (no parent): "
                                  + GetHierarchyPath(t) + ". Leaving unconverted");
                skipped++;
                continue;
            }

            var srcMesh = mf.sharedMesh;
            var mesh = UnityEngine.Object.Instantiate(srcMesh);
            mesh.name = srcMesh.name;

            var weights = new BoneWeight[mesh.vertexCount];
            for (int i = 0; i < weights.Length; i++)
                weights[i] = new BoneWeight { boneIndex0 = 0, weight0 = 1f };
            mesh.boneWeights = weights;
            // bindpose: 変換前と同じ見た目になるよう、
            // bone.localToWorld * bindpose == t.localToWorld を満たす行列を選ぶ
            // (非スキン時と同じワールド座標を、単一ボーンのスキニングで再現する)
            mesh.bindposes = new[] { bone.worldToLocalMatrix * t.localToWorldMatrix };

            var mats = mr.sharedMaterials;
            var wasEnabled = mr.enabled;

            UnityEngine.Object.DestroyImmediate(mr);
            UnityEngine.Object.DestroyImmediate(mf);

            var smr = t.gameObject.AddComponent<SkinnedMeshRenderer>();
            smr.sharedMesh = mesh;
            smr.bones = new[] { bone };
            smr.rootBone = bone;
            smr.sharedMaterials = mats;
            smr.enabled = wasEnabled;

            n++;
            Debug.Log("D2P: [Unskin] converted MeshRenderer to SkinnedMeshRenderer (owning bone="
                       + bone.name + "): " + GetHierarchyPath(t));
        }
        if (n > 0 || skipped > 0)
            Debug.Log("D2P: non-skinned mesh to SkinnedMeshRenderer conversion complete, converted " + n + ", "
                       + "skipped " + skipped + " (owning bone undeterminable)");
    }

    // dev#1369: 頂点ごとのボーン加重合成(Linear Blend Skinning)の純粋計算部分。
    // UnityEngine.Matrix4x4に依存せず16要素の列優先(column-major、Unity Matrix4x4の
    // 内部レイアウトと同じ)float配列で行列を表現し、dotnetハーネスで直接検証できる
    // ようにする(tests/unity_exporter/test_thirdparty_init_guard.pyと同じ抽出方式)。
    // 呼び出し側(FlattenSkinnedMeshes)はUnity.Matrix4x4<->float[16]変換の薄いアダプタ
    // (FlattenBoneMatrixToFloats/FlattenBoneMatrixFromFloats)を介してこれを使う。
    // D2P_FLATTENBLEND_PURE_BEGIN
    // 単位行列(16要素、列優先)
    internal static float[] FlattenBlendIdentity16()
    {
        var m = new float[16];
        m[0] = 1f; m[5] = 1f; m[10] = 1f; m[15] = 1f;
        return m;
    }

    // 複数ボーン行列(boneMats16[boneIndex] = 16要素の列優先行列、Σ wᵢ・boneMats16[i]の
    // "boneMats16[i]"側に相当。呼び出し側で既に bones[i].localToWorldMatrix * bindposes[i]
    // まで計算済みの値を渡すこと)を、頂点1個分のボーンインデックス/ウェイト(classic
    // BoneWeight方式、最大4本)で加重合成する。ウェイト合計がおよそ1でなければ合計で
    // 正規化する(データ品質のばらつき対策)。該当ボーンが無い/ウェイト0の枠は無視する。
    // 全ウェイトが0の頂点(ウェイト未設定の孤立頂点)は単位行列(無変換)にフォールバックする。
    internal static float[] FlattenBlendVertexMatrix(float[][] boneMats16, int[] boneIndices, float[] weights)
    {
        float total = 0f;
        for (int k = 0; k < weights.Length; k++) total += weights[k];
        if (total < 1e-6f)
            return FlattenBlendIdentity16();

        var acc = new float[16];
        for (int k = 0; k < weights.Length; k++)
        {
            float w = weights[k];
            if (w <= 0f) continue;
            int bi = boneIndices[k];
            if (bi < 0 || bi >= boneMats16.Length || boneMats16[bi] == null) continue;
            var bm = boneMats16[bi];
            for (int e = 0; e < 16; e++) acc[e] += bm[e] * w;
        }
        if (Math.Abs(total - 1f) > 1e-4f)
        {
            for (int e = 0; e < 16; e++) acc[e] /= total;
        }
        return acc;
    }

    // 「全ボーン行列が実質同一(=個別ボーン編集の無い、未編集リグ)」かどうかを判定する。
    // 真ならFlattenSkinnedMeshesは高速パス(旧実装と数値的に一致する単一行列適用)を使い、
    // 既存の無編集アバターの輸出結果を変えない。偽(=いずれかのボーンが個別編集されている)
    // なら、本物のスキニング式(頂点ごとのボーンウェイト加重合成)で焼く。
    internal static bool FlattenBlendAllApproxEqual(float[][] mats16, float eps)
    {
        if (mats16.Length == 0) return true;
        var first = mats16[0];
        if (first == null) return false;
        for (int i = 1; i < mats16.Length; i++)
        {
            var m2 = mats16[i];
            if (m2 == null) continue;  // nullボーンは比較対象外(既存実装と同じ扱い)
            for (int e = 0; e < 16; e++)
                if (Math.Abs(m2[e] - first[e]) > eps) return false;
        }
        return true;
    }

    // dev#1465フォローアップ(v2.11.1 relgate回帰対処): 頂点1個分のボーン
    // ウェイト(classic BoneWeight、最大4本)から「実際にスキニングへ寄与する
    // ボーン」を`used`配列へマークする。weight<=0または範囲外indexは無視する
    // (クラッシュしない・無関係ボーンを汚染しない)。
    //
    // 狙い: FlattenBlendAllApproxEqualによる「全ボーン行列が実質同一か」判定を、
    // どの頂点からも重み0でしか参照されないボーン(Humanoidの"_end"参照/tip骨等、
    // bones[]/bindposes[]配列には含まれるがスキニングには一切使われないもの)の
    // 影響から切り離すために使う。未使用ボーンの行列が他ボーンとどれだけ
    // ずれていても、そのずれは頂点の最終位置に一切寄与しないため、「編集の
    // 有無」の判定対象から除外するのが構造的に正しい(v2.11.1 relgate回帰、
    // flatapron検体のHead_R.003_end実例: このボーンはbones[0]と1mm超ずれて
    // いるが、どの頂点からもweight=0でしか参照されない未使用ボーンだった。
    // これを判定対象に含めていたため、未編集のリグが高速パスから外れて
    // LBS(低速)パスへ落ち、法線の計算方法が変わり見た目がわずかに変化して
    // いた)。判定対象(何を"編集"とみなすか)をこの関数で構造的に正しくする
    // (未使用ボーンの汚染を除去する)のが本関数の役割で、これはeps閾値の
    // 調整(呼び出し側FlattenSkinnedMeshesで別途対応、深いボーン階層の
    // 浮動小数点誤差吸収)とは独立した別軸の修正。
    internal static void FlattenBlendMarkBoneUsed(bool[] used, int boneIndex, float weight)
    {
        if (weight <= 0f) return;
        if (boneIndex < 0 || boneIndex >= used.Length) return;
        used[boneIndex] = true;
    }
    // D2P_FLATTENBLEND_PURE_END

    static float[] FlattenBoneMatrixToFloats(Matrix4x4 m)
    {
        var a = new float[16];
        for (int c = 0; c < 4; c++)
            for (int row = 0; row < 4; row++)
                a[c * 4 + row] = m[row, c];
        return a;
    }

    static Matrix4x4 FlattenBoneMatrixFromFloats(float[] a)
    {
        var m = new Matrix4x4();
        for (int c = 0; c < 4; c++)
            for (int row = 0; row < 4; row++)
                m[row, c] = a[c * 4 + row];
        return m;
    }

    // Unityのスキニングはノード変換を無視してバインド行列で解決するが、Blenderの
    // FBXインポータはスキンメッシュをアーマチュア配下へローカル行列ごと付け替える
    // ため、ノード変換とバインドが食い違うリグ(Armatureスケール等)は
    // メッシュとスケルトンの大きさ・向きが合わなくなる(2026-07-22実測)。
    // → 頂点をバインド時ワールド座標へ変換した複製メッシュを作り、bindposesも
    //   現在のボーンワールドから再計算、ノードはルート直下の恒等に置く。
    //   これで「どの行列を信じるインポータ」でも同じ配置になる
    //
    // dev#1369: 旧実装は bones[0](Humanoidでは通常Hips)1本だけの行列を全頂点へ
    // 一様に適用する剛体焼きだったため、Head縮小・足延長等のbones[0]以外への個別
    // ボーン編集が構造的に反映されなかった(.devonly\docs\rd\rd_1369_bonescale\
    // MECHANISM.md参照)。本物のスキニング式 Σ wᵢ・bones[i].localToWorldMatrix・
    // bindposes[i]・v で頂点ごとに焼くよう修正。ただし全ボーン行列が実質同一(=
    // 個別編集の無い、これまでどおりの大多数のケース)であれば、旧実装と数値的に
    // 一致する単一行列の高速パスへ自動的に落ちる(無退行、既存の無編集アバター
    // 輸出結果を変えない)。FBXへ書き出す各ノードのlocalScaleは従来どおり
    // BakeUniformScale()で1へ正規化されるため、非一様ボーンスケールがFBXへ
    // 直接乗ることは無い(segment scale compensate地雷を回避、聖域どおり)。
    static void FlattenSkinnedMeshes(GameObject root)
    {
        foreach (var r in root.GetComponentsInChildren<SkinnedMeshRenderer>(false))
        {
            if (r.sharedMesh == null || r.bones == null || r.bones.Length == 0)
                continue;
            var src = r.sharedMesh;
            var bp = src.bindposes;
            if (bp == null || bp.Length == 0 || r.bones[0] == null) continue;

            // dev#1369: 各ボーンの「現在ワールド行列×bindpose」を求める
            // (MECHANISM.md記載の式)。個別編集の無い未ポーズrigでは全ボーンで
            // この値が一致する(旧実装の「posed rig?」検算と同じ性質を、警告だけで
            // 終わらせず実際の分岐条件として使う)。
            int boneCount = bp.Length;
            var boneMats = new Matrix4x4[boneCount];
            var boneMatFloats = new float[boneCount][];
            for (int b = 0; b < boneCount; b++)
            {
                Matrix4x4 mb = (b < r.bones.Length && r.bones[b] != null)
                    ? r.bones[b].localToWorldMatrix * bp[b]
                    : Matrix4x4.identity;
                boneMats[b] = mb;
                boneMatFloats[b] = FlattenBoneMatrixToFloats(mb);
            }

            // dev#1465フォローアップ: ウェイトデータは判定のために先に取得する
            // (以前はLBSパスに落ちてから遅延取得していたが、判定自体に必要に
            // なった)。取得できない/頂点数と不整合なケースは「どのボーンが
            // 未使用か判定できない」ので、安全側(疑わしきは旧経路)としてすべての
            // ボーンをused扱いにし、旧来どおり全ボーン厳格一致判定へ倒す。
            BoneWeight[] vertexWeights = src.boneWeights;
            bool weightsAvailable = vertexWeights != null && vertexWeights.Length == src.vertexCount;
            var boneUsed = new bool[boneCount];
            if (weightsAvailable)
            {
                for (int i = 0; i < vertexWeights.Length; i++)
                {
                    var bw = vertexWeights[i];
                    FlattenBlendMarkBoneUsed(boneUsed, bw.boneIndex0, bw.weight0);
                    FlattenBlendMarkBoneUsed(boneUsed, bw.boneIndex1, bw.weight1);
                    FlattenBlendMarkBoneUsed(boneUsed, bw.boneIndex2, bw.weight2);
                    FlattenBlendMarkBoneUsed(boneUsed, bw.boneIndex3, bw.weight3);
                }
            }
            else
            {
                for (int b = 0; b < boneCount; b++) boneUsed[b] = true;
            }

            // dev#1465フォローアップ: 一致判定は「実際にスキニングへ使われる
            // ボーン」だけに限定する(bones[0]自身は旧実装が常にこれを使うため
            // 無条件で含める)。未使用ボーン(weight=0でしか参照されない
            // "_end"参照/tip骨等)の行列のずれは頂点の最終位置に一切寄与しない
            // ため、判定対象から除外するのが構造的に正しい(flatapron検体の
            // Head_R.003_end実例、v2.11.1 relgate回帰)。
            var uniformCheckMats = new List<float[]> { boneMatFloats[0] };
            for (int b = 1; b < boneCount; b++)
            {
                if (boneUsed[b] && boneMatFloats[b] != null)
                    uniformCheckMats.Add(boneMatFloats[b]);
            }
            // dev#1465フォローアップ: eps=1e-4はHumanoidボーン階層を何段も
            // 辿った実在検体(flatapron/flatver.1.01のkarada/mohu、指先・肩・
            // 脚など)では厳しすぎ、実測で0.0001〜0.0003程度の浮動小数点誤差
            // (深い行列連鎖のTransform.localToWorldMatrix蓄積誤差、意図的な
            // 編集ではない)がこれを上回り、無編集アバターまでLBS(低速)パスへ
            // 落ちてNCC回帰を起こしていた(v2.11.1 run_20260815_112850、
            // work\wp_1465_stability\NOTES.md実測)。1e-3は数値を新規に
            // 発明したものではなく、旧実装(#1369以前)が「posed rig?」の
            // 検算に使っていた並進成分の閾値0.001fそのもの(このアバターの
            // 単位系で「編集かもしれないので警告するが実害は無い」と既に
            // 判定されていた基準)を全16要素へ流用したもの。意図的な編集
            // (Head localScale=0.5、要素差分は最大で約0.5)とは3桁以上の
            // 差があり、疑わしきは旧経路(高速パス)へ倒すという方針を保ちつつ
            // 実在検体の無退行を回復する。
            bool uniformRig = FlattenBlendAllApproxEqual(uniformCheckMats.ToArray(), 1e-3f);

            if (!uniformRig && !weightsAvailable)
            {
                // 通常は起きないはずの防御的フォールバック(ウェイトデータが
                // 頂点数と不整合)。安全側として旧来どおりbones[0]由来の
                // 単一行列適用に落とす。
                Debug.LogWarning("D2P: FlattenSkinnedMeshes: boneWeights unavailable/mismatched, "
                                  + "falling back to rigid bone-0 transform: " + r.name);
                uniformRig = true;
            }
            else if (!uniformRig)
            {
                Debug.Log("D2P: FlattenSkinnedMeshes: per-bone edit detected (bind matrices differ), "
                          + "baking with full per-vertex skinning: " + r.name);
            }
            Matrix4x4 uniformM = boneMats[0];

            var mesh = UnityEngine.Object.Instantiate(src);
            mesh.name = src.name;
            var verts = mesh.vertices;
            var normals = mesh.normals;
            bool hasNormals = normals != null && normals.Length == verts.Length;

            // シーンで設定された現在のブレンドシェイプ値を頂点へ焼き込む。
            // MA構成では服をアバター体型に合わせるシェイプがシーン側で
            // 設定されていることが多い(toto実測: 未焼き込みだと服が体型に合わない)。
            //
            // dev#1168(2026-08-09、ラボ機能「シェイプキー」): 以前はここで
            // 「1件でも焼き込んだら(baked>0)ClearBlendShapes()で全ブレンド
            // シェイプを破棄」していたため、シーン側で未使用(重み0)の
            // ブレンドシェイプ自体はUnity輸出FBXまで残っていた可能性がある
            // ものの、そのデルタ座標はこの下のベイクポーズ変換(dev#1369以降は
            // 頂点ごとの変換行列vm/vnm)を一切受けずローカル座標のまま素通りして
            // いた(=座標が壊れた状態でしかFBXに乗らなかった)。パイプライン既定側は
            // Blender step01のdrop_shape_keys()が無条件で全dropしていたため実害は
            // 出ていなかったが、②案(BSありでexportし、Blender側で選択
            // 焼き込み+drop)を採るにはデルタも同じ変換行列で正しく
            // 変換して持ち込む必要がある。焼き込み対象(重み!=0)のブレンド
            // シェイプはこれまでどおりverts/normalsへ吸収して破棄する一方、
            // 未使用(重み0)のブレンドシェイプは、そのフレームデータを
            // Clear前に読み出しておき、ベイクポーズ変換の後で正しい行列
            // (vm[i]=頂点位置用、vnm[i]=法線用)を使って再構築する。
            int baked = 0;
            var keptShapeNames = new List<string>();
            var keptShapeFrameWeights = new List<float>();
            var keptShapeDeltaVerts = new List<Vector3[]>();
            var keptShapeDeltaNormals = new List<Vector3[]>();
            int shapeCountBeforeClear = mesh.blendShapeCount;
            for (int s = 0; s < shapeCountBeforeClear; s++)
            {
                float w = r.GetBlendShapeWeight(s);
                int frame = mesh.GetBlendShapeFrameCount(s) - 1;
                if (Mathf.Abs(w) < 1e-4f)
                {
                    // 未使用: フレームデータを保持して後で(変換後に)再構築する。
                    // 多フレームのブレンドシェイプは最終フレームのみを対象とする
                    // (直上の焼き込み処理と同じ簡略化、WP指示書の明示許容)。
                    float kfw = mesh.GetBlendShapeFrameWeight(s, frame);
                    var kdv = new Vector3[verts.Length];
                    var kdn = new Vector3[verts.Length];
                    mesh.GetBlendShapeFrameVertices(s, frame, kdv, kdn, null);
                    keptShapeNames.Add(mesh.GetBlendShapeName(s));
                    keptShapeFrameWeights.Add(kfw);
                    keptShapeDeltaVerts.Add(kdv);
                    keptShapeDeltaNormals.Add(hasNormals ? kdn : null);
                    continue;
                }
                float fw = mesh.GetBlendShapeFrameWeight(s, frame);
                float k = fw > 1e-4f ? w / fw : w / 100f;
                var dv = new Vector3[verts.Length];
                var dn = new Vector3[verts.Length];
                mesh.GetBlendShapeFrameVertices(s, frame, dv, dn, null);
                for (int i = 0; i < verts.Length; i++)
                    verts[i] += dv[i] * k;
                if (hasNormals)
                    for (int i = 0; i < normals.Length; i++)
                        normals[i] += dn[i] * k;
                baked++;
            }
            if (shapeCountBeforeClear > 0)
            {
                mesh.ClearBlendShapes();  // 焼き込み済み分+保持分とも一旦全破棄(下で保持分だけ再構築)
                if (baked > 0)
                    Debug.Log("D2P: baked blend shapes: " + r.name + " " + baked + " shape(s)");
            }

            // dev#1369: 頂点ごとの変換行列(uniformRigなら全頂点で同一=旧実装と数値的に
            // 一致、そうでなければ頂点のボーンウェイトで加重合成した本物のスキニング行列)。
            // 後段のブレンドシェイプdelta再構築でも同じ配列を再利用する。
            var vm = new Matrix4x4[verts.Length];
            var vnm = hasNormals ? new Matrix4x4[verts.Length] : null;
            for (int i = 0; i < verts.Length; i++)
            {
                Matrix4x4 vi = uniformRig
                    ? uniformM
                    : FlattenBoneMatrixFromFloats(FlattenBlendVertexMatrix(
                        boneMatFloats,
                        new[] { vertexWeights[i].boneIndex0, vertexWeights[i].boneIndex1,
                                vertexWeights[i].boneIndex2, vertexWeights[i].boneIndex3 },
                        new[] { vertexWeights[i].weight0, vertexWeights[i].weight1,
                                vertexWeights[i].weight2, vertexWeights[i].weight3 }));
                vm[i] = vi;
                verts[i] = vi.MultiplyPoint3x4(verts[i]);
                if (hasNormals)
                {
                    Matrix4x4 ni = uniformRig ? uniformM.inverse.transpose : vi.inverse.transpose;
                    vnm[i] = ni;
                    normals[i] = ni.MultiplyVector(normals[i]).normalized;
                }
            }
            mesh.vertices = verts;
            if (hasNormals)
                mesh.normals = normals;
            // dev#1168: 保持しておいた未使用ブレンドシェイプを、対応する頂点と
            // 同じ変換行列(vm[i]/vnm[i]、dev#1369で頂点ごとに変わりうる)で
            // 再構築する。デルタ(差分ベクトル)なので位置変換に平行移動は
            // 使わない(MultiplyVector、MultiplyPoint3x4ではない)。法線側デルタは
            // 既存の頂点法線変換と同様vnm[i]を使うが、デルタ自体は単位ベクトルとは
            // 限らないため正規化はしない。
            for (int ks = 0; ks < keptShapeNames.Count; ks++)
            {
                var kdv = keptShapeDeltaVerts[ks];
                var tdv = new Vector3[kdv.Length];
                for (int i = 0; i < kdv.Length; i++)
                    tdv[i] = vm[i].MultiplyVector(kdv[i]);
                Vector3[] tdn = null;
                if (hasNormals && keptShapeDeltaNormals[ks] != null)
                {
                    var kdn = keptShapeDeltaNormals[ks];
                    tdn = new Vector3[kdn.Length];
                    for (int i = 0; i < kdn.Length; i++)
                        tdn[i] = vnm[i].MultiplyVector(kdn[i]);
                }
                mesh.AddBlendShapeFrame(
                    keptShapeNames[ks], keptShapeFrameWeights[ks], tdv, tdn, null);
            }
            var newBp = new Matrix4x4[bp.Length];
            for (int b = 0; b < bp.Length; b++)
                newBp[b] = (b < r.bones.Length && r.bones[b] != null)
                    ? r.bones[b].worldToLocalMatrix : Matrix4x4.identity;
            mesh.bindposes = newBp;
            mesh.RecalculateBounds();
            r.sharedMesh = mesh;
            var t = r.transform;
            t.SetParent(root.transform, false);
            t.localPosition = Vector3.zero;
            t.localRotation = Quaternion.identity;
            t.localScale = Vector3.one;
        }
    }

    // dev#1551 laneC2(条件2/3の既知の赤①②の根治): 素体骨格に実在する「重み無し
    // 末端マーカー」骨(典型例: Humanoidの"_end"チップ骨。耳先端・尻尾先端・
    // 指先端・目・頬・足首等、どのメッシュ頂点からも一切参照されない、純粋な
    // 位置マーカーとしての末端Transform)が、Unity輸出FBXに到達する前の
    // どの製品コードでも削除されていないにも関わらず、輸出済みFBXの時点で
    // 既にArmatureのボーンとして存在しない(=消滅している)ことを実測で特定した
    // (work\run_1551\gate\ の4点比較: オラクルcomodo.fbx→Unity輸出FBXの間で
    // 既に21件の"_end"骨が消え、Blender step01は無罪。work\run_1551\laneC2\
    // NOTES.md参照)。
    //
    // 根本原因(com.unity.formats.fbx@4.2.1 Editor\FbxExporter.cs 実読で確定):
    // ExportSkinnedMesh()はSkinnedMeshRenderer.bones[]配列を直接走査して
    // ExportBoneTransform()を呼ぶだけで(1103-1144行)、ウェイトの有無は一切
    // 見ない——つまり「bones[]に載っているかどうか」だけがFbxSkeleton
    // (LimbNode、ボーンとして書き出される)になるかどうかを決めている。
    // comodoの"_end"チップ骨は、どのSkinnedMeshRendererのbones[]配列にも
    // 一度も登録されていない(頂点ウェイト0で登録されている、という従来の
    // 想定=dev#1465コメントの「_end参照/tip骨等」は別アバターの別事例であり、
    // comodoには当てはまらない。実機ヘッドレス検証で確認: Blenderインポート後
    // parent_type=BONE, parent_bone=正しい親名で正しい位置に来るが、
    // arm.data.bonesには載らないEMPTYとして出てくる=Unity側でNull型
    // ノードとして書かれている証拠)。そのためFbxExporterからは「骨ではない
    // 単なるTransform」として扱われ、Null型ノードとして書き出され、
    // BlenderのFBXインポータはNull型ノードをArmatureのボーンに変換しない
    // (Empty objectになるだけ)。
    //
    // 対策: 「祖先にボーン(CollectBoneTransformsの定義)を持ち、自身は
    // 子を持たない葉であり、実データ保持コンポーネント(Mesh/Renderer/
    // Animator等)も持たない」という構造条件(名前に一切依存しない。
    // CollapseNestedArmatureContainersの逆パターン=途中のNullではなく
    // 末端のNullを検出する)でこの種のマーカーを機械的に検出し、その親骨を
    // bones[]に含む最初のSkinnedMeshRendererへ、0ウェイトのまま追加登録する。
    // 既存頂点のBoneWeightは末尾に追加した新規インデックスを一切参照しない
    // ため、スキニング結果(頂点位置・見た目)には不変(実害ゼロ、頂点データは
    // 一切触らない)。これによりExportSkinnedMesh()のbones[]走査に自然に
    // 乗るようになり、FbxExporterがLimbNodeとして書き出す。
    //
    // 呼び出し位置はFlattenSkinnedMeshesの直後(このメソッド末尾で全SMRの
    // sharedMeshが既にレンダラーごとの一意複製になっている段階)。共有
    // メッシュアセットを直接書き換えないよう、ここでも独立してInstantiate()
    // で複製してから書き換える(呼び出し順の変更に対しても安全側)。
    // RebindToCurrent(この関数の後段で呼ばれる)がbindposesを現在のボーン
    // ワールド行列から一括で取り直すため、ここで設定するbindposeの精度は
    // 重要ではない(後段で必ず上書きされる)。
    // D2P_LEAFMARKER_DETECT_BEGIN
    // 「重み無し末端マーカー」骨の検出条件のみを切り出した純粋な判定関数
    // (AttachLeafMarkerBones本体からメッシュ配列の書き換えを分離。
    // tests\unity_exporter\test_leaf_marker_bones_dev1551.pyがCollapseNested
    // ArmatureContainers系試験(test_nested_armature_fallback_dev876.py)と
    // 同じTransform/GameObjectスタブでこの関数単体を検証する)。
    // 条件: 「祖先にボーン(CollectBoneTransformsの定義)を持ち、自身は子を
    // 持たない葉であり、Transform以外のコンポーネントを一切持たない、
    // まだボーン扱いされていないTransform」。
    //
    // dev#1551緊急修理(work\run_1551\pgf_diag\RESULT.md): 当初はここで
    // HasEssentialNonTransformComponent(Collapse用途の「実データ保持型
    // [Mesh/Renderer/Animator]だけを除外する」判定)を流用していたが、
    // VRCPhysBoneCollider/PortableDynamicBoneCollider等の非表示コンポーネント
    // だけを持つTransformはHasEssentialNonTransformComponentでは「非essential」
    // となり誤ってマーカー候補に含まれてしまう。実例(PGF.prefab):
    // PBColliders直下の"Spine"という名のPhysBoneColliderアンカーが、D2Pの
    // 物理骨処理で実SpineボーンA自身の子へ再親付けされ、"Spine_2"へ改名
    // された上でFindLeafMarkerBonesに"_end"チップ骨と誤認され、後段の
    // Blender側tail修正が実Spineをゼロ長化→Blenderが黙って実Spineを破棄する
    // という致命的リグレッションを起こした。
    // コンポーネント名を黒リストへ追加する対処は次の未知コンポーネントで
    // 同じ事故を再発させるため、「Transform以外を一切持たない裸のTransform
    // だけがマーカー候補たりうる」という構造条件へ一般化する
    // (HasAnyNonTransformComponent、下記)。真の"_end"チップ骨はUnity側で
    // 意図的に何もアタッチしない空Transformとして作られるため、この条件でも
    // 従来どおり検出される。
    static bool HasAnyNonTransformComponent(Transform t)
    {
        foreach (var c in t.GetComponents<Component>())
        {
            // missing script(c==null)は「何かが付いていた形跡」として安全側で
            // 「コンポーネント有り」扱いにする(裸のTransformとは断定しない)。
            if (c == null) return true;
            if (c.GetType() == typeof(Transform)) continue;
            return true;
        }
        return false;
    }

    static List<Transform> FindLeafMarkerBones(GameObject root, HashSet<Transform> bones, Component primaryAnimator)
    {
        var all = new List<Transform>();
        CollectAllTransforms(root.transform, all);
        var markers = new List<Transform>();
        foreach (var t in all)
        {
            if (t == root.transform) continue;
            if (bones.Contains(t)) continue;               // 既にボーン扱い
            if (t.childCount > 0) continue;                // 葉のみが対象(末端マーカー)
            if (HasAnyNonTransformComponent(t)) continue;   // Transform以外を何か1つでも持てば対象外(構造条件、黒リストではない)
            if (!HasAncestorBone(t, bones)) continue;       // 骨格から辿れない孤立ノードは対象外
            markers.Add(t);
        }
        return markers;
    }
    // D2P_LEAFMARKER_DETECT_END

    static List<KeyValuePair<Transform, Transform>> AttachLeafMarkerBones(GameObject root)
    {
        var result = new List<KeyValuePair<Transform, Transform>>();
        var bones = CollectBoneTransforms(root);
        if (bones.Count == 0) return result;
        var primaryAnimator = FindPrimaryAnimator(root);
        var markers = FindLeafMarkerBones(root, bones, primaryAnimator);
        if (markers.Count == 0) return result;

        int attachedCount = 0;
        var attachedOnce = new HashSet<Transform>();
        foreach (var r in root.GetComponentsInChildren<SkinnedMeshRenderer>(false))
        {
            if (r.sharedMesh == null || r.bones == null || r.bones.Length == 0) continue;
            var boneSet = new HashSet<Transform>(r.bones);
            var toAdd = new List<Transform>();
            foreach (var m in markers)
            {
                if (attachedOnce.Contains(m)) continue;     // 既に他のレンダラーへ登録済み(1箇所で足りる)
                if (m.parent != null && boneSet.Contains(m.parent))
                    toAdd.Add(m);
            }
            if (toAdd.Count == 0) continue;

            var src = r.sharedMesh;
            var mesh = UnityEngine.Object.Instantiate(src);
            mesh.name = src.name;
            var oldBones = r.bones;
            var oldBp = src.bindposes;
            int oldLen = oldBones.Length;
            var newBones = new Transform[oldLen + toAdd.Count];
            var newBp = new Matrix4x4[oldLen + toAdd.Count];
            Array.Copy(oldBones, newBones, oldLen);
            Array.Copy(oldBp, newBp, Math.Min(oldLen, oldBp.Length));
            for (int i = 0; i < toAdd.Count; i++)
            {
                var m = toAdd[i];
                newBones[oldLen + i] = m;
                newBp[oldLen + i] = m.worldToLocalMatrix * r.transform.localToWorldMatrix;
                attachedOnce.Add(m);
                result.Add(new KeyValuePair<Transform, Transform>(m, m.parent));
            }
            mesh.bindposes = newBp;
            r.sharedMesh = mesh;
            r.bones = newBones;
            attachedCount += toAdd.Count;
        }
        if (attachedCount > 0)
            Debug.Log("D2P: attached " + attachedCount + " zero-weight leaf marker bone(s) "
                + "(e.g. Humanoid \"_end\" tip transforms) to SkinnedMeshRenderer.bones[] so "
                + "Unity FbxExporter writes them as skeleton LimbNodes instead of dropping them "
                + "as plain Null nodes (dev#1551 condition 2 fix)");
        var unattached = markers.FindAll(m => !attachedOnce.Contains(m));
        if (unattached.Count > 0)
            Debug.LogWarning("D2P: " + unattached.Count + " leaf marker bone(s) could not be "
                + "attached to any SkinnedMeshRenderer.bones[] (their parent bone is not itself "
                + "registered in any renderer's bones[] array); they will still export as plain "
                + "Null nodes: " + string.Join(", ", unattached.ConvertAll(m => GetHierarchyPath(m))));
        return result;
    }

    // dev#1551 laneC2続き: AttachLeafMarkerBonesが登録したマーカー骨は、Blenderの
    // FBXインポータでArmatureのボーンとしては正しく復元されるものの(head位置は
    // 常に正しい)、tail(骨の長さ)はBlender側の「子が無い葉ボーンは親と同じ
    // 長さ・方向へ延長する」という既定ヒューリスティックに委ねられる。このヒュー
    // リスティックは親ボーンが「子が複数(マーカー+MergeArmatureが付けた無関係な
    // 服骨等)」を持つ場合に不安定になり(どの子を基準に長さを決めるか一意に
    // 定まらない)、親自身の長さがオラクルと食い違うケースが実測で見つかった
    // (Hips.001: オラクル9.1cmに対し目視上は正しく見えるはずが、$guid服骨が
    // 兄弟として同居しているため半分弱の4.6cmへ短縮される。work\run_1551\
    // laneC2\NOTES.md参照)。step01_import_vrm.py側で、このサイドカー
    // (マーカー名→親ボーン名)を読み、親のtailをマーカーの現在位置(head位置は
    // 常に正しいため信頼できる)へ明示的に上書きすることで、この曖昧さを
    // Blenderのヒューリスティックに委ねず決定的に解消する(次のマーカー自身の
    // tailも同じ理屈で親のベクトルを複製して復元する)。
    static void WriteLeafMarkerBonesSidecar(string outDir, List<KeyValuePair<Transform, Transform>> pairs)
    {
        if (pairs == null || pairs.Count == 0) return;
        var sb = new StringBuilder();
        sb.Append("{\n  \"format\": \"divetopalworld-leafmarkerbones-1\",\n  \"markers\": {\n");
        for (int i = 0; i < pairs.Count; i++)
        {
            sb.AppendFormat("    \"{0}\": \"{1}\"{2}\n",
                J(pairs[i].Key.name), J(pairs[i].Value.name), i < pairs.Count - 1 ? "," : "");
        }
        sb.Append("  }\n}\n");
        File.WriteAllText(Path.Combine(outDir, "leaf_marker_bones.json"), sb.ToString(),
            new UTF8Encoding(false));
    }

    // FBX ExporterはスケルトンルートをeRootで書き、BlenderのFBXインポータは
    // eRootをアーマチュアオブジェクト化するためルートボーン(Hips)が消える
    // (2026-07-21実測)。Hipsの上に恒等ダミーを挟み、eRootをダミーへ吸わせる。
    // 戻り値: 挿入したダミーのTransform(非ヒューマノイド等で未挿入ならnull)。
    // RedirectRootBonesAwayFromSelfが全rootBoneの退避先をこの1点に統一するために使う
    // (dev#150、詳細は同メソッドのコメント参照)
    static Transform InsertSkeletonRootDummy(GameObject root)
    {
        var animator = root.GetComponentInChildren<Animator>();
        if (animator == null || animator.avatar == null || !animator.avatar.isHuman)
            return null;
        var hips = animator.GetBoneTransform(HumanBodyBones.Hips);
        if (hips == null || hips.parent == null) return null;
        var dummy = new GameObject("d2p_skeleton_root");
        dummy.transform.SetParent(hips.parent, false);
        dummy.transform.localPosition = Vector3.zero;
        dummy.transform.localRotation = Quaternion.identity;
        dummy.transform.localScale = Vector3.one;
        dummy.transform.SetSiblingIndex(hips.GetSiblingIndex());
        hips.SetParent(dummy.transform, true);
        return dummy.transform;
    }

    // 2026-07-26実測(FbxExporter.cs 3133-3155行): あるSkinnedMeshRendererの
    // rootBoneが「そのメッシュ自身のボーン」かつ「そのメッシュのbones[]に
    // 含まれる子ボーンを持つ」場合、そのボーンのFbxSkeletonはeRoot型で
    // 書き出される。BlenderのFBXインポータ(import_fbx.py find_armatures)は
    // eRoot型ノードを見つけるたびに独立したarmatureオブジェクトへ変換する
    // 仕様のため、Hipsだけでなく「各パーツ固有のrootBone」(実測: wiskerの
    // Head、PannAcc装飾品のBone等)でも同一の症状が起き、対応する
    // armature_setupエントリが無いままKeyErrorになる(InsertSkeletonRootDummy
    // でHipsの上にダミーを挟むだけでは、Hips自身のFbxSkeleton型は変わらず
    // 効かない。かつHips以外のrootBoneには元々対策していなかった)。
    //
    // dev#150(2026-07-30): 退避先を「rootBoneの直接の親」にする実装は誤り
    // だった。rootBoneがHipsそのものならparent=d2p_skeleton_root(非ボーンの
    // 安全な着地点)になるので問題無いが、rootBoneが骨格の途中にある
    // パーツ固有ボーン(実測41件中の一部)の場合、parentは大抵また別の
    // 「実ボーン」でしかない。その実ボーンへeRootを付け替えると、今度は
    // そのボーン自身が「祖先にも子孫にもボーンがいる非ボーン扱いの
    // ノード」というCollapseNestedArmatureContainers対象そのものの構造を
    // 新規に作ってしまう——だが同メソッドは本処理より前(この関数の前段)
    // にしか実行されないため、この新規発生分は誰にも解消されない。
    // Blender io_scene_fbx の find_armatures() はis_boneの子への探索しか
    // 行わない(非ボーンの子孫を再帰的に見つけに行かない)ため、この
    // 新設ノードは armature 化されないままcollect_skeleton_meshesの
    // 素通し集計だけがメッシュを外側のarmature(=d2p_skeleton_root)へ
    // 誤帰属させ、mesh.armature_setup[self]がKeyErrorになる
    // (2026-07-30、Blender単体でのFBX往復再現で確認済み: work\wp150\)。
    //
    // 修正: rootBoneの退避先を「その場その場の直接の親」ではなく、
    // InsertSkeletonRootDummyが挿した単一の恒等ダミー(skeletonRootDummy)
    // へ常に統一する。rootBoneは境界ボックス計算等にのみ使われスキニング
    // 結果には影響しないため(既存実測どおり)、どのメッシュも同じ1つの
    // 安全な非ボーン祖先を指すようにすれば、新規のeRootノードは
    // d2p_skeleton_root以外に一切発生しなくなる(dummyが無い=非ヒューマノイド
    // 等の場合のみ、次善としてrb.parentへフォールバック)
    static void RedirectRootBonesAwayFromSelf(GameObject root, Transform skeletonRootDummy)
    {
        int n = 0;
        foreach (var r in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            var rb = r.rootBone;
            if (rb == null || r.bones == null || rb.parent == null) continue;
            bool hasChildBoneInThisMesh = false;
            foreach (Transform c in rb)
            {
                if (Array.IndexOf(r.bones, c) >= 0) { hasChildBoneInThisMesh = true; break; }
            }
            if (!hasChildBoneInThisMesh) continue;
            r.rootBone = skeletonRootDummy != null ? skeletonRootDummy : rb.parent;
            n++;
        }
        if (n > 0)
            Debug.Log("D2P: redirected rootBone for " + n + " renderer(s), "
                + (skeletonRootDummy != null ? "to shared dummy" : "to own parent")
                + " (eRoot avoidance): ");
    }

    // Blenderのfind_armatures()は「ボーンではないNull/Root祖先」を見つけるたびに
    // 独立armatureへ変換するが、既にボーンチェーンの内部にネストされた非ボーン
    // コンテナ(子孫にボーンを持つNull)はこの走査経路(ボーン境界を跨がない
    // トップダウン探索)から構造的に外れてしまい、collect_armature_meshesの
    // 既知の集計漏れ(import_fbx.py内 "See T70244" コメント)でメッシュだけが
    // 親armatureのmeshes一覧に混入し、対応するarmature_setupが無いままKeyError
    // になる(2026-07-26実測、PanWisker/Armature/Head(内側)/WiskerParent_L…で発生)。
    // 該当コンテナ(自身はボーンではないが子孫にボーンを持ち、かつ祖先にも
    // ボーンがいる=ネストされたarmatureルート)を検出し、子を1段上へ直結して
    // コンテナ自体を消すことでボーンチェーンを途切れさせない。
    // ワールド座標は不変(worldPositionStays:trueで再親化するため見た目は無変化)。
    // 収縮可否の基準はStripNonEssentialPostBakeと同一の必須5型リストを参照する
    // HasEssentialNonTransformComponentに統一する(dev#455)。この判定が走る時点
    // (BakeNdmf後・StripNonEssentialPostBake前)では、Merge Armatureが揺れ物
    // (PhysBone)付き装飾品のために生成するアンカーノードがまだVRCPhysBone等の
    // コンポーネントを持ったままのため、「Transform以外は一切禁止」という
    // 旧基準(コンポーネント数==1)では収縮対象から漏れ、FBXへ残存してBlender側で
    // KeyErrorになっていた。新基準はTransform以外の実データ保持型(Animator/
    // SkinnedMeshRenderer/MeshRenderer/MeshFilter)だけを収縮不可の理由にし、
    // どうせ140行目のStripNonEssentialPostBakeで除去される型(PhysBone等)は
    // 収縮を妨げない。
    // dev#876再調査(2026-08-03): 「KeyError: d2p_skeleton_root」は3ユーザー・
    // 5回以上再発しており、dev#455/dev#876の各修正は"判明した個別トリガー"を
    // 1つずつ潰してきたに過ぎない(Merge Armatureアンカー→残置Animator付き
    // コンテナ、の順)。この収縮アルゴリズムが「ボーンかどうか」を判定する
    // 基準は、従来はSkinnedMeshRenderer.bones[]への参照だけだった。しかし
    // 実際にBlenderのFBXインポータがLimbNode(ボーン)扱いするかどうかは
    // Unity FBX Exporter内部の判定であり、bones[]配列への参照だけでは
    // 捕捉しきれない可能性がある(rootBoneだけが指す骨、Humanoidボーンとして
    // 登録されているがどのSkinnedMeshRendererからも直接参照されない骨=
    // twist骨や未使用の終端骨等)。CollapseNestedArmatureContainersと
    // AssertNoNestedArmatureContainersRemain(輸出直前の不変条件チェック)の
    // 両方がこの1箇所を共有することで、「ボーン」の定義がこの先ズレて再発する
    // (dev#455がIsEssentialComponentTypeを共有化した時と同じ轍)ことを防ぐ。
    // D2P_COLLAPSE455_ALGO_BEGIN
    static HashSet<Transform> CollectBoneTransforms(GameObject root)
    {
        var bones = new HashSet<Transform>();
        foreach (var r in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            if (r.bones != null)
                foreach (var b in r.bones)
                    if (b != null) bones.Add(b);
            if (r.rootBone != null) bones.Add(r.rootBone);  // bones[]に無くrootBoneだけが指すケースを補う
        }
        // Humanoidボーンとして登録されている骨は、どのSkinnedMeshRendererからも
        // 直接参照されていなくても(twist骨・未使用の終端骨等)ボーン扱いにする
        var animator = root.GetComponentInChildren<Animator>();
        if (animator != null && animator.avatar != null && animator.avatar.isHuman)
        {
            foreach (HumanBodyBones hb in Enum.GetValues(typeof(HumanBodyBones)))
            {
                if (hb == HumanBodyBones.LastBone) continue;
                var bt = animator.GetBoneTransform(hb);
                if (bt != null) bones.Add(bt);
            }
        }
        return bones;
    }

    static void CollapseNestedArmatureContainers(GameObject root)
    {
        var bones = CollectBoneTransforms(root);
        if (bones.Count == 0) return;

        var primaryAnimator = FindPrimaryAnimator(root);  // dev#876: 輸出ルート自身のAnimatorだけを保護対象にする

        var all = new List<Transform>();
        CollectAllTransforms(root.transform, all);

        int n = 0;
        // 深い側(子)から処理するため末尾から辿る(親を先に潰すと判定がずれるため)
        for (int i = all.Count - 1; i >= 0; i--)
        {
            var t = all[i];
            if (t == root.transform) continue;
            if (bones.Contains(t)) continue;                   // 自身がボーンなら対象外
            if (HasEssentialNonTransformComponent(t, primaryAnimator)) continue; // 実データ保持型(輸出ルート自身のAnimator/SkinnedMeshRenderer/MeshRenderer/MeshFilter)を持つなら触らない
            if (!HasAncestorBone(t, bones)) continue;          // ボーンチェーンの内部でなければ対象外
            if (!HasDescendantBone(t, bones)) continue;        // 子孫にボーンが無ければ対象外

            var parent = t.parent;
            var children = new List<Transform>();
            foreach (Transform c in t) children.Add(c);
            foreach (var c in children)
                c.SetParent(parent, true);                     // ワールド座標維持で1段上へ
            UnityEngine.Object.DestroyImmediate(t.gameObject);
            n++;
        }
        if (n > 0)
            Debug.Log("D2P: collapsed " + n + " nested armature container(s) (linked bone chain directly)");
    }

    static void CollectAllTransforms(Transform t, List<Transform> outList)
    {
        outList.Add(t);
        foreach (Transform c in t) CollectAllTransforms(c, outList);
    }

    static bool HasAncestorBone(Transform t, HashSet<Transform> bones)
    {
        for (var p = t.parent; p != null; p = p.parent)
            if (bones.Contains(p)) return true;
        return false;
    }

    static bool HasDescendantBone(Transform t, HashSet<Transform> bones)
    {
        foreach (Transform c in t)
        {
            if (bones.Contains(c)) return true;
            if (HasDescendantBone(c, bones)) return true;
        }
        return false;
    }
    // D2P_COLLAPSE455_ALGO_END

    // D2P_NESTED_ARMATURE_INVARIANT_BEGIN
    // dev#876再調査(2026-08-03オーナー裁定): 「次でなおす、というのは次はないということ」。
    // CollapseNestedArmatureContainersは現時点で判明しているトリガー(dev#455のPhysBone付き
    // アンカー、dev#876の残置Animator)を潰すが、未知の6番目のトリガーが
    // あっても(例: 実データ保持型コンポーネントが直接付いたコンテナ、
    // CollectBoneTransformsでも捕捉しきれないボーン判定の穴等)、それを事前に
    // 全て列挙することはできない。そのため、収縮処理が全て終わった
    // 輸出直前の最終階層を再度走査し、「祖先にも子孫にもボーンを持つ
    // 非ボーンノード(=Blenderの find_armatures() が見つけられずに
    // mesh.armature_setup[self] がKeyErrorになる構造)が1件でも残っていないかを
    // 強制する不変条件チェック。残っていた場合、収縮できなかった
    // 理由(実データ保持型のため意図的に未収縮か、CollectBoneTransformsの
    // 見落としか)を問わず、輸出を中断して該当ノードのパスを名指しした
    // 明確な例外で止める(Blenderの謎のKeyErrorとして何時間後かに再発見される
    // 事態を避ける)。別途dev#925相当の「輸出直前の不変条件表明」をこの
    // 1本で具体化する。
    static void AssertNoNestedArmatureContainersRemain(GameObject root)
    {
        var bones = CollectBoneTransforms(root);
        Debug.Log("D2P: [InvariantCheck] armature structure: bone count=" + bones.Count);
        if (bones.Count == 0) return;

        var primaryAnimator = FindPrimaryAnimator(root);
        var all = new List<Transform>();
        CollectAllTransforms(root.transform, all);

        var violations = new List<string>();
        foreach (var t in all)
        {
            if (t == root.transform) continue;
            if (bones.Contains(t)) continue;
            if (!HasAncestorBone(t, bones)) continue;
            if (!HasDescendantBone(t, bones)) continue;
            // ここに到達した時点で「非ボーン・祖先ボーンあり・子孫ボーンあり」
            // のネストされたarmatureコンテナが輸出直前まで残っている
            string reason = HasEssentialNonTransformComponent(t, primaryAnimator)
                ? "intentionally not collapsed because it holds a real-data component"
                : "cause unknown (CollectBoneTransforms' bone judgment may not match the actual "
                  + "Unity FBX Exporter's LimbNode judgment; needs investigation)";
            violations.Add(GetHierarchyPath(t) + " (" + reason + ")");
        }
        if (violations.Count > 0)
        {
            throw new Exception(
                "aborting export: " + violations.Count + " nested armature container(s) "
                + "(non-bone node(s) with bones in both ancestors and descendants) remain "
                + "right before export. Exporting FBX in this state fails in Blender's FBX "
                + "importer with 'KeyError: d2p_skeleton_root' (same mechanism as "
                + "dev#150/dev#455/dev#876). Affected path(s):\n  " + string.Join("\n  ", violations));
        }
    }
    // D2P_NESTED_ARMATURE_INVARIANT_END

    // D2P_BONES_SANITIZE_BEGIN
    // dev#1607: 重複入れ子Armature構造(本体Armature以外に同名ボーンチェーンを
    // 持つ入れ子Armatureを複数含むprefab。衣装/アクセサリが独自骨格コピーを
    // 同梱する構成)を統合(CollapseNestedArmatureContainers/
    // CleanupClothesBonesPreBake等)した後、いずれかのSkinnedMeshRendererの
    // bones[]配列に「無効な」ボーン参照が残ることがある。
    //
    // 実機調査で確定した機構(com.unity.formats.fbx@4.2.1、FbxExporter.cs実読+
    // tests\unity_exporter\manual_repro\D2P1607Repro.cs で再現・確定、
    // work\wp_1607_notes\NOTES.md参照): 当初は「bones[]要素がC# null(破棄済みTransform参照)である
    // こと」自体が原因と推測したが、実機検証の結果これは誤り——Unity公式Exporterは
    // 真nullのbones[]要素を明示的にガードしており(ExportSkeleton/ExportSkin/
    // ExportSkinnedMesh、いずれも`if (bone != null)`)、警告ログを出すだけで
    // 正常に輸出を継続する。
    // 実際にArgumentNullExceptionが発生する条件は、**bones[]要素(null出ない、
    // 生きているTransform)自身の`.parent`がnullであること**。ExportBoneTransform
    // (FbxExporter.cs:3164)が「親のbindposeを取得する」ために
    // `GetBindPose(unityBone.parent, ...)`を無条件に呼び出しており、GetBindPose
    // 自身は`unityBone.parent==null`のケースを冒頭で防御している(1061行、
    // 「親を持たないボーンはworldToLocalMatrixをそのままbindposeにする」設計)
    // にもかかわらず、ExportBoneTransform側はunityBone自身の親が無いケースを
    // 考慮せず`unityBone.parent`(=null)をそのままGetBindPoseへ渡してしまう
    // (Unity公式パッケージ側の未対応ケース)。GetBindPose内部でnullを1040行の
    // `boneToBindPose.TryGetValue(unityBone=null, ...)`に渡した時点で
    // ArgumentNullExceptionになる(dev#1607本文・33FLAL34/NYABD3GPのスタック
    // トレースと完全一致、D2P1607Repro.RunOrphanBoneCaseで実測済み)。
    // 「親を持たないTransform」は通常は輸出ルート自身(go.transform、シーン上の
    // トップレベルで親を持たないのが普通)くらいしか無く、本体ボーン(Hips等)は
    // 常にArmature配下でparent!=nullのはずだが、CollapseNestedArmatureContainers/
    // CleanupClothesBonesPreBake等の骨格統合処理が絡んだ結果、何らかのボーンが
    // bones[]に登録されたまま親を失う(または輸出ルート自身がbones[]に紛れ込む)
    // 経路がありうる、というのがissueの一般化された原因の実体と判断する。
    // 同種の「親を持たないボーンがrootBoneになる」パターン自体は既にdev#150/
    // InsertSkeletonRootDummy/RedirectRootBonesAwayFromSelfで対策済みだが、
    // それらはExportUnifiedFbxより前(輸出ルート直前のInsertSkeletonRootDummy)の
    // 段階でrootBoneフィールドだけを見て対処するものであり、bones[]配列内の
    // 任意の要素(rootBoneでなくてもよい)が親を失うケースまではカバーしていない。
    //
    // 対策: Unity公式Exporterへ渡す直前の最終防衛として、全SkinnedMeshRenderer
    // のbones[]配列から「null要素」と「親を持たない(parent==null)要素」の両方を
    // 検出し、除去する。除去後はボーンインデックスが前へ詰まるため、頂点の
    // BoneWeightが指すインデックスも付随して再マップし(除去されたボーンを
    // 指していた頂点はウェイト0扱いへ無害化)、mesh.bindposesも同じ並びへ整合
    // させる。r.rootBoneフィールド自体は変更しない(bones[]配列からの除去のみ。
    // ExportBoneTransformはbones[]配列の走査からのみ呼ばれるため、rootBone
    // フィールド単体を残してもクラッシュ経路には乗らない)。
    //
    // 「本体骨格の同名ボーンへ再解決」(issue推奨案のもう一方)はここでは行わない:
    // 親を失った時点で元の(統合前の)所属関係の情報が失われており、名前ベースの
    // 再解決先を安全に特定する手掛かりが無いため(推測で任意のボーンへ繋ぎ直す
    // 方が誤結線のリスクが高く安全側ではない)。除去のみが構造的に安全に実行
    // できる対処であり、頂点データ(見た目)への影響は「元々そのボーンへの
    // 寄与があった頂点のウェイトがゼロになる」のみ(dev#1607の対象ケースは
    // そもそも統合処理で無効化された無ウェイト/再配線漏れボーンであり、実害は
    // 無いか極小と判断する)。
    static int SanitizeSkinnedMeshBonesBeforeExport(GameObject root)
    {
        int totalRemoved = 0;
        foreach (var r in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            if (r.sharedMesh == null || r.bones == null || r.bones.Length == 0) continue;
            var bones = r.bones;
            bool anyInvalid = false;
            for (int i = 0; i < bones.Length; i++)
                if (IsInvalidSanitizeBone(bones[i])) { anyInvalid = true; break; }
            if (!anyInvalid) continue;

            var src = r.sharedMesh;
            var oldBp = src.bindposes;
            int oldLen = bones.Length;
            var remap = new int[oldLen];  // 旧インデックス -> 新インデックス(除去された場合-1)
            var newBonesList = new List<Transform>();
            var newBpList = new List<Matrix4x4>();
            int removedHere = 0;
            for (int i = 0; i < oldLen; i++)
            {
                if (IsInvalidSanitizeBone(bones[i]))
                {
                    remap[i] = -1;
                    removedHere++;
                    continue;
                }
                remap[i] = newBonesList.Count;
                newBonesList.Add(bones[i]);
                newBpList.Add(i < oldBp.Length ? oldBp[i] : Matrix4x4.identity);
            }

            var mesh = UnityEngine.Object.Instantiate(src);
            mesh.name = src.name;
            var weights = mesh.boneWeights;
            if (weights != null && weights.Length == mesh.vertexCount)
            {
                for (int v = 0; v < weights.Length; v++)
                {
                    var bw = weights[v];
                    // BoneWeight.weight0-3は(新しいUnity APIでは)自動実装プロパティであり
                    // refを直接渡せないため、いったんローカル変数へ退避してから渡す
                    float w0 = bw.weight0, w1 = bw.weight1, w2 = bw.weight2, w3 = bw.weight3;
                    bw.boneIndex0 = RemapSanitizedBoneIndex(remap, bw.boneIndex0, ref w0);
                    bw.boneIndex1 = RemapSanitizedBoneIndex(remap, bw.boneIndex1, ref w1);
                    bw.boneIndex2 = RemapSanitizedBoneIndex(remap, bw.boneIndex2, ref w2);
                    bw.boneIndex3 = RemapSanitizedBoneIndex(remap, bw.boneIndex3, ref w3);
                    bw.weight0 = w0; bw.weight1 = w1; bw.weight2 = w2; bw.weight3 = w3;
                    weights[v] = bw;
                }
                mesh.boneWeights = weights;
            }
            mesh.bindposes = newBpList.ToArray();
            r.sharedMesh = mesh;
            r.bones = newBonesList.ToArray();

            Debug.LogWarning("D2P: [BonesSanitize] " + GetHierarchyPath(r.transform) + ": removed "
                + removedHere + " invalid bone reference(s) (null, or parentless/orphaned Transform) "
                + "from SkinnedMeshRenderer.bones[] before FBX export (dev#1607: leftover reference "
                + "after nested armature collapse/cleanup; Unity's official FBX Exporter would throw "
                + "ArgumentNullException in GetBindPose otherwise, since ExportBoneTransform "
                + "unconditionally dereferences bone.parent)");
            totalRemoved += removedHere;
        }
        if (totalRemoved > 0)
            Debug.Log("D2P: BonesSanitize complete, removed " + totalRemoved
                + " invalid bone reference(s) total across all SkinnedMeshRenderer(s) (dev#1607)");
        return totalRemoved;
    }

    // 「無効」の定義: null、または親を持たない(parent==null)生きたTransform
    // (Unity公式FBX Exporterの既知のクラッシュ条件、上のコメント参照)。
    static bool IsInvalidSanitizeBone(Transform b)
    {
        return b == null || b.parent == null;
    }

    // 除去されたボーン(remap[oldIndex]==-1)を指していたウェイトはゼロ化して
    // インデックス0(常に存在する)へ無害に付け替える。範囲外インデックスも
    // 同様に安全側で処理する(本来Unity側で起き得ないはずだが防御的に扱う)。
    static int RemapSanitizedBoneIndex(int[] remap, int oldIndex, ref float weight)
    {
        if (oldIndex < 0 || oldIndex >= remap.Length) { weight = 0f; return 0; }
        int mapped = remap[oldIndex];
        if (mapped >= 0) return mapped;
        weight = 0f;
        return 0;
    }
    // D2P_BONES_SANITIZE_END

    // com.unity.formats.fbx の ModelExporter でベイク後の実体を1本のFBXへ。
    // パッケージ参照を増やさないためreflectionで呼ぶ。
    // 重要: 既定のExportObject(string,Object)はASCII FBXを吐き、BlenderはASCII FBXを
    // 読めない(2026-07-21実測)。必ずBinary指定のオプションを組んで渡す
    static string ExportUnifiedFbx(GameObject go, string outDir)
    {
        SanitizeSkinnedMeshBonesBeforeExport(go);  // dev#1607: 公式Exporterへ渡す直前の最終防衛
        var t = FindType("UnityEditor.Formats.Fbx.Exporter.ModelExporter");
        if (t == null)
            throw new Exception(
                "FBX Exporter (com.unity.formats.fbx) is not installed. " +
                "Run via export_from_unity.ps1, or add it via Package Manager.");
        var safe = new StringBuilder();
        foreach (var ch in go.name)
            safe.Append(Array.IndexOf(Path.GetInvalidFileNameChars(), ch) >= 0 ? '_' : ch);
        string fbxName = safe + ".fbx";
        string path = Path.Combine(outDir, fbxName).Replace("\\", "/");

        // Binary指定オプション(4.x: 内部ExportModelSettingsSerialize / 5.x: 公開ExportModelOptions)
        object opts = null;
        foreach (var typeName in new[] {
            "UnityEditor.Formats.Fbx.Exporter.ExportModelOptions",
            "UnityEditor.Formats.Fbx.Exporter.ExportModelSettingsSerialize" })
        {
            var ot = t.Assembly.GetType(typeName);
            if (ot == null) continue;
            var candidate = Activator.CreateInstance(ot, true);
            if (SetFormatBinary(candidate)) { opts = candidate; break; }
        }
        if (opts == null)
            throw new Exception("cannot construct FBX Exporter binary output options (incompatible version)");
        // Maya互換命名(スペースや.を_へ変換)を無効化。humanoid.jsonや製品FBXと
        // ボーン名が食い違う事故の元(2026-07-21実測: "Upper Leg.L"→"Upper_Leg_L")
        if (!TrySetOption(opts, "SetUseMayaCompatibleNames", "UseMayaCompatibleNames",
                          "mayaCompatibleNaming", false))
            Debug.LogWarning("D2P: could not disable Maya-compatible naming (bone names may be converted)");

        // (string, 対象, ..., オプション, ...) を受けるExportObject/ExportObjectsを探して呼ぶ
        string result = null;
        bool invoked = false;
        foreach (var mi in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
        {
            if (mi.Name != "ExportObject" && mi.Name != "ExportObjects") continue;
            var ps = mi.GetParameters();
            if (ps.Length < 3 || ps[0].ParameterType != typeof(string)) continue;
            int optIdx = -1;
            for (int i = 2; i < ps.Length; i++)
                if (ps[i].ParameterType.IsAssignableFrom(opts.GetType())) { optIdx = i; break; }
            if (optIdx < 0) continue;
            var args = new object[ps.Length];
            args[0] = path;
            if (ps[1].ParameterType == typeof(UnityEngine.Object[]))
                args[1] = new UnityEngine.Object[] { go };
            else if (ps[1].ParameterType.IsAssignableFrom(typeof(GameObject)))
                args[1] = go;
            else
                continue;
            args[optIdx] = opts;  // 残りの引数はnull(省略可能なDictionary等)
            try
            {
                result = mi.Invoke(null, args) as string;
            }
            catch (TargetInvocationException tie)
            {
                // dev#194(SE48AGFP): 同居NDMFプラグインの静的初期化失敗がここで
                // TargetInvocationExceptionとして再発する実例を確認済み。
                // BuildInvocationFailureMessageの説明はBakeNdmf直前のコメント参照
                Debug.LogException(tie);
                throw new Exception(BuildInvocationFailureMessage("unified FBX export", tie));
            }
            invoked = true;
            break;
        }
        if (!invoked)
            throw new Exception("ModelExporter's Export-with-options overload not found (incompatible version)");
        if (result == null || !File.Exists(path))
            throw new Exception("failed to export unified FBX: " + path);
        // ASCIIで出ていないか検品(バイナリFBXは "Kaydara FBX Binary" マジックで始まる)
        var head = new byte[20];
        using (var fs = File.OpenRead(path)) fs.Read(head, 0, head.Length);
        if (Encoding.ASCII.GetString(head).IndexOf("Kaydara FBX Binary", StringComparison.Ordinal) != 0)
            throw new Exception("FBX is not in binary format (aborting since Blender cannot read it)");
        return fbxName;
    }

    // オプションオブジェクトのExportFormatをBinaryへ(4.x/5.xの実装差をまとめて吸収)
    // dev#518: 生のreflection呼び出しをtry/catch無しで行うと内部でNREが起きた際に
    // 無言のTargetInvocationExceptionとして落ち、診断不能になる(BakeNdmf/
    // ExportUnifiedFbxのExportObject呼び出しと同じ轍)。同ファイル既存の
    // catch (TargetInvocationException tie) パターンで保護する
    static bool SetFormatBinary(object opts)
    {
        const BindingFlags F = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
        for (var t = opts.GetType(); t != null; t = t.BaseType)
        {
            var m = t.GetMethod("SetExportFormat", F);
            if (m != null && m.GetParameters().Length == 1)
            {
                try
                {
                    m.Invoke(opts, new[] { EnumBinary(m.GetParameters()[0].ParameterType) });
                }
                catch (TargetInvocationException tie)
                {
                    Debug.LogException(tie);
                    throw new Exception(BuildInvocationFailureMessage("binary output option setup (SetExportFormat)", tie));
                }
                return true;
            }
            var p = t.GetProperty("ExportFormat", F);
            if (p != null && p.CanWrite && p.PropertyType.IsEnum)
            {
                try
                {
                    p.SetValue(opts, EnumBinary(p.PropertyType), null);
                }
                catch (TargetInvocationException tie)
                {
                    Debug.LogException(tie);
                    throw new Exception(BuildInvocationFailureMessage("binary output option setup (ExportFormat property)", tie));
                }
                return true;
            }
            var f = t.GetField("exportFormat", F);
            if (f != null && f.FieldType.IsEnum)
            {
                try
                {
                    f.SetValue(opts, EnumBinary(f.FieldType));
                }
                catch (TargetInvocationException tie)
                {
                    Debug.LogException(tie);
                    throw new Exception(BuildInvocationFailureMessage("binary output option setup (exportFormat field)", tie));
                }
                return true;
            }
        }
        return false;
    }

    // オプションオブジェクトの任意設定をsetterメソッド/プロパティ/フィールドの順で試す
    // dev#518: SetFormatBinaryと同様の理由でTargetInvocationExceptionを保護する
    static bool TrySetOption(object opts, string setterName, string propName,
                             string fieldName, object value)
    {
        const BindingFlags F = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
        for (var t = opts.GetType(); t != null; t = t.BaseType)
        {
            var m = t.GetMethod(setterName, F);
            if (m != null && m.GetParameters().Length == 1)
            {
                try
                {
                    m.Invoke(opts, new[] { value });
                }
                catch (TargetInvocationException tie)
                {
                    Debug.LogException(tie);
                    throw new Exception(BuildInvocationFailureMessage("option setup (" + setterName + ")", tie));
                }
                return true;
            }
            var p = t.GetProperty(propName, F);
            if (p != null && p.CanWrite)
            {
                try
                {
                    p.SetValue(opts, value, null);
                }
                catch (TargetInvocationException tie)
                {
                    Debug.LogException(tie);
                    throw new Exception(BuildInvocationFailureMessage("option setup (" + propName + ")", tie));
                }
                return true;
            }
            var f = t.GetField(fieldName, F);
            if (f != null)
            {
                try
                {
                    f.SetValue(opts, value);
                }
                catch (TargetInvocationException tie)
                {
                    Debug.LogException(tie);
                    throw new Exception(BuildInvocationFailureMessage("option setup (" + fieldName + ")", tie));
                }
                return true;
            }
        }
        return false;
    }

    static object EnumBinary(Type enumType)
    {
        try { return Enum.Parse(enumType, "Binary"); }
        catch { return Enum.ToObject(enumType, 1); }  // ExportFormat { ASCII=0, Binary=1 }
    }

    // dev#250(オーナー裁定2026-07-30、実報告Z8XBKJBC): prefab→Unity輸出だけは
    // 成功したのに、Rig設定(Configure Avatar)で必須HumanBoneが未割当のまま保存
    // されたアバターが実在する(isHuman==trueでも起こりうる、dev#233実測)。
    // 従来はhumanoid.jsonに当該キーが載らないまま素通りし、Blender側
    // (step01_import_vrm.py)の内部pal名FATALで初めて発覚していた
    // (dev#233が対応するのはそのメッセージの改善で、本機能が拾いきれなかった
    // 場合の最終フォールバックという関係になる)。
    // ここではUnity輸出の時点で、未割当の必須ボーンを実スケルトンの
    // Transform名から「命名規約辞書」で名前ベース推定して補完する
    // (オーナー指示: "humanoid取得は名前を取るだけの話")。
    // 追加裁定(2026-07-30): 「曖昧なら止まってユーザーに聞く」。候補が複数
    // (曖昧)・ゼロの場合は自動選択せず、対話できる経路(Unity Editorの
    // Export Avatarメニュー実行)ではダイアログで選ばせ、対話できない経路
    // (バッチ実行)では候補+対処法(bone_overrides.json)を提示して停止する。
    // 誤割当のまま黙って変換するより安全側に倒す方針。
    // 判定ロジック(SuggestBoneName/FindNearMisses/ResolveRequiredBone)は
    // Unity非依存(GameObject等を使わない)の純粋関数として実装し、
    // dotnetでコンパイル・実行して検証できるようにする
    // (tests\unity_exporter\test_bone_name_suggest.py)。
    // D2P_BONESUGGEST_PURE_BEGIN
    internal enum BoneSuggestStatus { Matched, Ambiguous, NotFound }

    internal struct BoneSuggestResult
    {
        public BoneSuggestStatus Status;
        public string BoneName;
        public List<string> Candidates;
    }

    // ResolveRequiredBoneの決定結果。Sourceは "already_assigned"(既に割当済み・
    // 無変更)/ "override"(bone_overrides.json指定)/ "suggested"(名前から自動推定)/
    // "override_invalid"(overrides指定がこのアバターに存在しない)/
    // "unresolved"(自動では決められない。呼び出し側がユーザーに聞く)
    internal struct BoneAssignmentDecision
    {
        public bool Assigned;
        public string BoneName;
        public string Source;
        public BoneSuggestStatus Status;
        public List<string> Candidates;
    }

    // Unity標準humanName(HumanTrait.BoneName相当)→ 各流儀での代表的な別名。
    // 大文字小文字・区切り文字(_ . : - 空白)のゆらぎはNormalizeBoneTokenで
    // 吸収するため、ここでは代表形を1つずつ書けば十分(Unityの自動マッピング
    // 相当の素直な実装。過剰なパターン網羅はしない)。対象は必須11ボーン
    // (pipeline\blender\step01_import_vrm.pyの必須チェック対象と一致させる)
    internal static readonly Dictionary<string, string[]> RequiredHumanBoneAliases =
        new Dictionary<string, string[]>
    {
        { "Hips", new[] { "Hips", "J_Bip_C_Hips", "Pelvis", "腰", "骨盤" } },
        { "Spine", new[] { "Spine", "J_Bip_C_Spine", "Spine1", "背骨" } },
        { "Head", new[] { "Head", "J_Bip_C_Head", "頭" } },
        { "LeftUpperArm", new[] { "LeftUpperArm", "UpperArm.L", "UpperArm_L",
            "LeftArm", "mixamorig:LeftArm", "J_Bip_L_UpperArm", "左腕", "左上腕" } },
        { "RightUpperArm", new[] { "RightUpperArm", "UpperArm.R", "UpperArm_R",
            "RightArm", "mixamorig:RightArm", "J_Bip_R_UpperArm", "右腕", "右上腕" } },
        { "LeftHand", new[] { "LeftHand", "Hand.L", "Hand_L", "mixamorig:LeftHand",
            "J_Bip_L_Hand", "左手" } },
        { "RightHand", new[] { "RightHand", "Hand.R", "Hand_R", "mixamorig:RightHand",
            "J_Bip_R_Hand", "右手" } },
        { "LeftUpperLeg", new[] { "LeftUpperLeg", "UpperLeg.L", "UpperLeg_L",
            "LeftUpLeg", "mixamorig:LeftUpLeg", "J_Bip_L_UpperLeg", "左太もも", "左腿" } },
        { "RightUpperLeg", new[] { "RightUpperLeg", "UpperLeg.R", "UpperLeg_R",
            "RightUpLeg", "mixamorig:RightUpLeg", "J_Bip_R_UpperLeg", "右太もも", "右腿" } },
        { "LeftFoot", new[] { "LeftFoot", "Foot.L", "Foot_L", "mixamorig:LeftFoot",
            "J_Bip_L_Foot", "左足首", "左足" } },
        { "RightFoot", new[] { "RightFoot", "Foot.R", "Foot_R", "mixamorig:RightFoot",
            "J_Bip_R_Foot", "右足首", "右足" } },
    };

    // エラー・ダイアログ表示用の日本語併記ラベル(dev#233と同じ方向性:
    // Unity側の人間可読名を出す)
    internal static readonly Dictionary<string, string> RequiredHumanBoneJaLabel =
        new Dictionary<string, string>
    {
        { "Hips", "Hips(腰/骨盤)" },
        { "Spine", "Spine(背骨)" },
        { "Head", "Head(頭)" },
        { "LeftUpperArm", "Left Upper Arm(左上腕)" },
        { "RightUpperArm", "Right Upper Arm(右上腕)" },
        { "LeftHand", "Left Hand(左手)" },
        { "RightHand", "Right Hand(右手)" },
        { "LeftUpperLeg", "Left Upper Leg(左太もも)" },
        { "RightUpperLeg", "Right Upper Leg(右太もも)" },
        { "LeftFoot", "Left Foot(左足)" },
        { "RightFoot", "Right Foot(右足)" },
    };

    // 区切り文字(_ . : - 空白)を除去し小文字化する。Mixamo("mixamorig:LeftFoot")・
    // Blender式("Foot.L"/"Foot_L")・VRoid("J_Bip_L_Foot")の表記ゆれを1つの
    // 比較形へ正規化する(日本語はそのまま、大文字小文字も区切りも無いため無害)
    internal static string NormalizeBoneToken(string s)
    {
        if (string.IsNullOrEmpty(s)) return "";
        var sb = new StringBuilder(s.Length);
        foreach (var ch in s)
        {
            if (ch == '_' || ch == '.' || ch == ':' || ch == '-' || ch == ' ') continue;
            sb.Append(char.ToLowerInvariant(ch));
        }
        return sb.ToString();
    }

    // humanName(Unity標準表記、例"LeftFoot")に対し、実スケルトンのボーン名
    // 一覧から名前ベースで候補を探す。0件=NotFound、2件以上(異なる実名が
    // 別名辞書に一致)=Ambiguous、1件のみ=Matched。同一名の重複出現は1件と数える
    internal static BoneSuggestResult SuggestBoneName(string humanName,
        IEnumerable<string> actualBoneNames)
    {
        string[] aliases;
        if (!RequiredHumanBoneAliases.TryGetValue(humanName, out aliases))
            return new BoneSuggestResult
            { Status = BoneSuggestStatus.NotFound, Candidates = new List<string>() };

        var normalizedAliases = new HashSet<string>();
        normalizedAliases.Add(NormalizeBoneToken(humanName));
        foreach (var a in aliases) normalizedAliases.Add(NormalizeBoneToken(a));

        var matches = new List<string>();
        foreach (var actual in actualBoneNames)
        {
            if (string.IsNullOrEmpty(actual)) continue;
            if (normalizedAliases.Contains(NormalizeBoneToken(actual)) && !matches.Contains(actual))
                matches.Add(actual);
        }
        if (matches.Count == 0)
            return new BoneSuggestResult { Status = BoneSuggestStatus.NotFound, Candidates = matches };
        if (matches.Count > 1)
            return new BoneSuggestResult { Status = BoneSuggestStatus.Ambiguous, Candidates = matches };
        return new BoneSuggestResult
        { Status = BoneSuggestStatus.Matched, BoneName = matches[0], Candidates = matches };
    }

    // 文字列編集距離(Levenshtein)。候補ゼロ時の「近い名前」ヒント計算に使う
    internal static int LevenshteinDistance(string a, string b)
    {
        int n = a.Length, m = b.Length;
        var d = new int[n + 1, m + 1];
        for (int i = 0; i <= n; i++) d[i, 0] = i;
        for (int j = 0; j <= m; j++) d[0, j] = j;
        for (int i = 1; i <= n; i++)
            for (int j = 1; j <= m; j++)
            {
                int cost = a[i - 1] == b[j - 1] ? 0 : 1;
                d[i, j] = Math.Min(Math.Min(d[i - 1, j] + 1, d[i, j - 1] + 1), d[i - 1, j - 1] + cost);
            }
        return d[n, m];
    }

    // 完全一致候補がゼロのときの参考表示専用(自動選択には使わない)。
    // 正規化後のLevenshtein距離が近いボーン名を最大maxResults件、近い順に返す
    internal static List<string> FindNearMisses(string humanName,
        IEnumerable<string> actualBoneNames, int maxResults = 5)
    {
        string[] aliases;
        if (!RequiredHumanBoneAliases.TryGetValue(humanName, out aliases))
            aliases = new string[0];
        var normAliases = new List<string> { NormalizeBoneToken(humanName) };
        foreach (var a in aliases) normAliases.Add(NormalizeBoneToken(a));

        var scored = new List<KeyValuePair<int, string>>();
        var seen = new HashSet<string>();
        foreach (var actual in actualBoneNames)
        {
            if (string.IsNullOrEmpty(actual) || !seen.Add(actual)) continue;
            var normActual = NormalizeBoneToken(actual);
            if (normActual.Length == 0) continue;
            int best = int.MaxValue;
            int bestAliasLen = 0;
            foreach (var na in normAliases)
            {
                if (na.Length == 0) continue;
                int d = LevenshteinDistance(na, normActual);
                if (d < best) { best = d; bestAliasLen = na.Length; }
            }
            if (best == int.MaxValue) continue;
            int longer = Math.Max(bestAliasLen, normActual.Length);
            int threshold = Math.Max(2, longer / 2);
            if (best <= threshold)
                scored.Add(new KeyValuePair<int, string>(best, actual));
        }
        scored.Sort((x, y) => x.Key.CompareTo(y.Key));
        var outList = new List<string>();
        for (int i = 0; i < scored.Count && i < maxResults; i++)
            outList.Add(scored[i].Value);
        return outList;
    }

    // 必須ボーン1個分の割当を決定する(Unity型に依存しない純粋ロジック)。
    // 優先順: ①authoritativeBoneName(呼び出し側がanimator.GetBoneTransform(
    // HumanBodyBones.X).nameで解決した、輸出直前リネーム後の実Transform参照
    // による現在名)が実骨格に存在するなら常にそれを最優先で採用する(dev#1226、
    // 実報告5WPE3V47)。②既に割当済み"かつ実骨格に存在"ならそれを尊重
    // (無変更。dev#879で実在確認を追加) ③bone_overrides.json指定が
    // あればそれを検証のうえ採用 ④名前から一意に推定できればそれを採用
    // ⑤それ以外(曖昧/候補ゼロ/override指定が実在しない)は自動で決めず、
    // 呼び出し側(Unity依存の配線)がheadlessならエラー、interactiveなら
    // ユーザーに選ばせる
    //
    // dev#1226(実報告5WPE3V47)の背景: existingBoneNameはAvatarアセットに
    // 保存された静的な文字列で、輸出直前のEnsureUniqueTransformNames
    // (dev#300)による一意化リネームを一切反映しない。アクセサリ骨格
    // (メガネ・衣装等が持つ独自Armature)が本体と同名のボーン(例: "hips")を
    // 持つ場合、階層走査順で先に生名を得た側が"hips"のまま残り、本体の
    // 真のボーンが"hips_2"等へリネームされる。従来の②(existingBoneNameが
    // 実骨格に「存在するかどうか」だけを見るチェック)は、この場合
    // アクセサリ側の同名ボーンにヒットしてしまい、本体とは無関係な
    // Transformをhumanoid.jsonへ書いてしまっていた(名前は一致するが
    // 同一Transformではない、という同一性チェックの欠如)。
    // authoritativeBoneNameはExportHumanoid内でhips_local計算と同じ
    // animator.GetBoneTransform(HumanBodyBones.X)というTransform参照による
    // 解決を経ているため、名前の偶然の一致に左右されない(既に実装・
    // 動作実績のあるAPIを流用するのみで新規依存は無い)
    internal static BoneAssignmentDecision ResolveRequiredBone(string humanName,
        string existingBoneName, Dictionary<string, string> overrides,
        IEnumerable<string> actualBoneNames, string authoritativeBoneName = null)
    {
        if (!string.IsNullOrEmpty(authoritativeBoneName))
        {
            bool authExists = false;
            foreach (var n in actualBoneNames)
                if (n == authoritativeBoneName) { authExists = true; break; }
            if (authExists)
                return new BoneAssignmentDecision
                { Assigned = true, BoneName = authoritativeBoneName, Source = "transform_resolved" };
            // Animator側は解決できたのに、その名前が実骨格一覧に見当たらない
            // 異常系(通常は起こらないはずだが、呼び出し側の取得ミス等の
            // 保険として)は、既存の解決経路(existingBoneName→override→
            // suggest)へそのままフォールバックする
        }

        if (!string.IsNullOrEmpty(existingBoneName))
        {
            bool existingExists = false;
            foreach (var n in actualBoneNames)
                if (n == existingBoneName) { existingExists = true; break; }
            if (existingExists)
                return new BoneAssignmentDecision
                { Assigned = true, BoneName = existingBoneName, Source = "already_assigned" };
            // dev#879(実報告K5XTWFUB): Configure Avatar時点では割当済みだった
            // ボーン名が、輸出された実FBX骨格には存在しないことがある(輸出後の
            // リネーム・別ツールでの再エクスポート等)。existingBoneNameを無条件に
            // 信用せず、override→名前推定→(headlessエラー/interactive選択)の
            // 既存の解決経路へそのまま合流させる(誤ったボーン名がhumanoid.jsonに
            // 素通りし、下流Blender工程でヒントの無いFATALになるのを防ぐ)
        }

        string overrideName;
        if (overrides != null && overrides.TryGetValue(humanName, out overrideName)
            && !string.IsNullOrEmpty(overrideName))
        {
            bool exists = false;
            foreach (var n in actualBoneNames)
                if (n == overrideName) { exists = true; break; }
            if (exists)
                return new BoneAssignmentDecision
                { Assigned = true, BoneName = overrideName, Source = "override" };
            return new BoneAssignmentDecision
            {
                Assigned = false, Source = "override_invalid",
                Candidates = new List<string> { overrideName }
            };
        }

        var result = SuggestBoneName(humanName, actualBoneNames);
        if (result.Status == BoneSuggestStatus.Matched)
            return new BoneAssignmentDecision
            { Assigned = true, BoneName = result.BoneName, Source = "suggested" };

        var candidates = result.Status == BoneSuggestStatus.Ambiguous
            ? result.Candidates
            : FindNearMisses(humanName, actualBoneNames, 5);
        return new BoneAssignmentDecision
        {
            Assigned = false, Source = "unresolved",
            Status = result.Status, Candidates = candidates
        };
    }

    // headless(バッチ実行、聞く経路が構造的に無い)向けの停止メッセージ。
    // dev#233と同じ方向性(Unity側の人間可読名+対処手順)を踏襲する
    internal static string BuildUnresolvedHeadlessMessage(string humanName,
        BoneAssignmentDecision decision, string outDir)
    {
        string label;
        if (RequiredHumanBoneJaLabel.TryGetValue(humanName, out label))
        {
            int paren = label.IndexOf('(');
            if (paren >= 0) label = label.Substring(0, paren).TrimEnd();
        }
        else
        {
            label = humanName;
        }
        var sb = new StringBuilder();
        sb.Append("Required Humanoid bone '" + label + "' is unassigned. ");
        if (decision.Source == "override_invalid")
        {
            sb.Append("The bone '" + decision.Candidates[0]
                + "' specified in bone_overrides.json was not found in this avatar's bone list. "
                + "Please specify it again with the exact name.");
        }
        else if (decision.Status == BoneSuggestStatus.Ambiguous)
        {
            sb.Append("Multiple candidates were found from the name and cannot be auto-selected " +
                "(stopping to avoid a wrong assignment). Candidates: "
                + string.Join(", ", decision.Candidates) + ".");
        }
        else
        {
            sb.Append("No bone matching the name was found.");
            if (decision.Candidates != null && decision.Candidates.Count > 0)
                sb.Append(" Similar name candidates: " + string.Join(", ", decision.Candidates) + ".");
        }
        sb.Append(" Fix: 1) select this avatar in the original Unity project and manually assign " +
            label + " via the Rig tab > Configure Avatar, then re-export, or " +
            "2) create bone_overrides.json in the output folder (" + outDir + ") specifying " +
            "{\"" + humanName + "\": \"<correct bone name>\"} and run again.");
        return sb.ToString();
    }
    // D2P_BONESUGGEST_PURE_END

    static readonly string[] RequiredHumanBoneNames = {
        "Hips", "Spine", "Head",
        "LeftUpperArm", "RightUpperArm", "LeftHand", "RightHand",
        "LeftUpperLeg", "RightUpperLeg", "LeftFoot", "RightFoot"
    };

    static string GetJaLabel(string humanName)
    {
        string label;
        return RequiredHumanBoneJaLabel.TryGetValue(humanName, out label) ? label : humanName;
    }

    // <outDir>\bone_overrides.json (任意、無ければ空扱い) を読む。
    // ユーザーが名前推定を待たず/推定に失敗した後で明示指定するための、
    // このツール専用の単純なフラット文字列マップ({"HumanName": "実ボーン名"})。
    // 形式を完全に自前で決められるため、外部JSONライブラリを増やさず
    // 正規表現で素直に読む(他所でJSON読込に使っている前例が無いため合わせて追加しない)
    static Dictionary<string, string> LoadBoneOverrides(string outDir)
    {
        var result = new Dictionary<string, string>();
        string path = Path.Combine(outDir, "bone_overrides.json");
        if (!File.Exists(path)) return result;
        string text = File.ReadAllText(path, Encoding.UTF8);
        foreach (Match m in Regex.Matches(text,
            "\"((?:[^\"\\\\]|\\\\.)*)\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\""))
        {
            result[UnescapeJsonString(m.Groups[1].Value)] = UnescapeJsonString(m.Groups[2].Value);
        }
        if (result.Count > 0)
            Debug.Log("D2P: loaded bone_overrides.json: " + result.Count + " entries (" + path + ")");
        return result;
    }

    static string UnescapeJsonString(string s)
    {
        return s.Replace("\\\"", "\"").Replace("\\\\", "\\");
    }

    // dev#1226: 必須HumanName(Unity標準表記、"Hips"等)からHumanBodyBones列挙値
    // への対応。ApplyBoneNameSuggestions内でanimator.GetBoneTransform(...)を
    // 呼ぶためだけの単純な対応表(RequiredHumanBoneNamesと1対1)
    static readonly Dictionary<string, HumanBodyBones> RequiredHumanBodyBoneEnum =
        new Dictionary<string, HumanBodyBones>
    {
        { "Hips", HumanBodyBones.Hips },
        { "Spine", HumanBodyBones.Spine },
        { "Head", HumanBodyBones.Head },
        { "LeftUpperArm", HumanBodyBones.LeftUpperArm },
        { "RightUpperArm", HumanBodyBones.RightUpperArm },
        { "LeftHand", HumanBodyBones.LeftHand },
        { "RightHand", HumanBodyBones.RightHand },
        { "LeftUpperLeg", HumanBodyBones.LeftUpperLeg },
        { "RightUpperLeg", HumanBodyBones.RightUpperLeg },
        { "LeftFoot", HumanBodyBones.LeftFoot },
        { "RightFoot", HumanBodyBones.RightFoot },
    };

    // 必須HumanBoneのうち未割当のものを、Transform参照解決→既存割当尊重→
    // bone_overrides.json→名前推定→(headlessならエラー/interactiveなら
    // ダイアログ)の順に解決する(dev#1226でTransform参照解決を最優先へ追加)。
    // humanは呼び出し側が用意したAvatar.humanDescription.humanの複製リストで、
    // ここで直接書き換える(実Avatarアセットには一切触れない)
    static void ApplyBoneNameSuggestions(GameObject go, Animator animator,
        List<HumanBone> human, string outDir)
    {
        var overrides = LoadBoneOverrides(outDir);
        List<Transform> actualBoneTransforms = null;
        List<string> actualBoneNames = null;

        foreach (var req in RequiredHumanBoneNames)
        {
            int idx = human.FindIndex(hb => hb.humanName == req);
            string existing = idx >= 0 ? human[idx].boneName : null;

            if (actualBoneNames == null)
            {
                actualBoneTransforms = new List<Transform>(go.GetComponentsInChildren<Transform>(true));
                actualBoneNames = actualBoneTransforms.ConvertAll(t => t.name);
            }

            // dev#1226: animator.GetBoneTransform(HumanBodyBones.X)による
            // Transform参照解決(hips_localの計算と同じAPI)。名前の偶然一致に
            // 依存しないため、輸出直前のEnsureUniqueTransformNamesリネーム後
            // でも正しい実体を指す
            string authoritative = null;
            HumanBodyBones hbEnum;
            if (animator != null && RequiredHumanBodyBoneEnum.TryGetValue(req, out hbEnum))
            {
                var t = animator.GetBoneTransform(hbEnum);
                if (t != null) authoritative = t.name;
            }

            var decision = ResolveRequiredBone(req, existing, overrides, actualBoneNames, authoritative);
            string resolvedName;

            if (decision.Assigned)
            {
                resolvedName = decision.BoneName;
                if (resolvedName == existing) continue;  // 無変更(出力不変を担保)
                string sourceLabel;
                if (decision.Source == "override")
                    sourceLabel = " assigned via bone_overrides.json: ";
                else if (decision.Source == "transform_resolved")
                    sourceLabel = " resolved via actual Transform reference (corrected mismatch from prior assignment): ";
                else
                    sourceLabel = " auto-assigned from name: ";
                Debug.Log("D2P: " + req + sourceLabel + resolvedName);
            }
            else if (decision.Source == "override_invalid")
            {
                throw new Exception(BuildUnresolvedHeadlessMessage(req, decision, outDir));
            }
            else if (UnityEngine.Application.isBatchMode)
            {
                // headless(バッチ実行): 誤割当のまま黙って進めるより、候補と
                // 対処法を提示して止める(オーナー裁定2026-07-30: 「曖昧なら
                // 止まってユーザーに聞く」。バッチには直接聞く経路が構造的に
                // 無いため、bone_overrides.jsonでの再指定を提示する)
                throw new Exception(BuildUnresolvedHeadlessMessage(req, decision, outDir));
            }
            else
            {
                // interactive(Unity EditorのExport Avatarメニュー実行): 勝手に
                // 選ばず、ユーザーに選ばせる(dev#236と同じ「ユーザー起点の対話
                // なら可」の扱い。起動時セットアップの押し付けモーダルとは異なる)
                resolvedName = BoneChoiceWindow.PickBone(GetJaLabel(req), decision.Status,
                    decision.Candidates ?? new List<string>(), actualBoneTransforms);
                if (resolvedName == null)
                    throw new Exception("D2P: " + GetJaLabel(req)
                        + " assignment was canceled; aborting export.");
                Debug.Log("D2P: " + req + " assigned via user selection: " + resolvedName);
            }

            if (idx >= 0)
            {
                var hb = human[idx];
                hb.boneName = resolvedName;
                human[idx] = hb;
            }
            else
            {
                human.Add(new HumanBone
                {
                    humanName = req,
                    boneName = resolvedName,
                    limit = new HumanLimit { useDefaultValues = true }
                });
            }
        }
    }

    // dev#919: Humanoid Avatarを持つAnimatorの選択。
    // 旧実装は go.GetComponentInChildren<Animator>() で「(非アクティブを
    // 除外した)最初に見つかった1個」を無条件採用しており、
    // (a) 非アクティブなGameObjectのAnimatorを見逃す
    // (b) 見つかった1個のAvatarが未設定/非Humanoidでも、他に有効な候補が
    //     階層内にあるかどうかを確かめずそのまま失敗にする
    // という2つの欠陥があった。輸出対象のGameObject階層には、輸出ルート
    // 自身のAnimator(Humanoid Avatar設定済み)以外に、衣装・ギミック等が
    // 独自に持ち込んだAnimator(Avatar未設定が普通)が同居しうる
    // (dev#919実例: 輸出ルート"PMF (1)"のAnimatorはHumanoid Avatar設定済み
    // だが、子"飛行雲"のAnimatorはAvatar未設定)。
    // ここでは非アクティブ含め全Animatorを走査し、Humanoid Avatar
    // (avatar != null && avatar.isHuman)を持つものだけを候補とし、
    // 輸出ルート自身を最優先、それ以外は階層走査順(GetComponentsInChildren
    // の深さ優先順)で先頭を選ぶ。
    // ユーザーのアバターは送ってもらえないため、ログだけで診断できる
    // ことが生命線(CLAUDE.md「問い合わせからのデバッグ」節)。成功・失敗を
    // 問わず、走査した全Animatorの情報(パス/輸出ルート自身か/avatarが
    // nullか/isHumanか)を必ずログへ残す。
    static Animator SelectHumanoidAnimator(GameObject go)
    {
        var candidates = go.GetComponentsInChildren<Animator>(true);
        if (candidates.Length == 0)
        {
            Debug.LogWarning("D2P: [Humanoid Avatar Select] no Animator found in export target hierarchy @ "
                + GetHierarchyPath(go.transform));
            return null;
        }

        var paths = new string[candidates.Length];
        var isRoot = new bool[candidates.Length];
        var avatarNull = new bool[candidates.Length];
        var isHuman = new bool[candidates.Length];
        for (int i = 0; i < candidates.Length; i++)
        {
            var a = candidates[i];
            paths[i] = GetHierarchyPath(a.transform);
            isRoot[i] = a.transform == go.transform;
            avatarNull[i] = a.avatar == null;
            isHuman[i] = !avatarNull[i] && a.avatar.isHuman;
            Debug.Log("D2P: [Humanoid Avatar Candidate] " + paths[i]
                + " isRoot=" + isRoot[i] + " avatarNull=" + avatarNull[i] + " isHuman=" + isHuman[i]);
        }

        int selected = -1;
        string reason = null;
        for (int i = 0; i < candidates.Length; i++)  // 第1優先: 輸出ルート自身+Humanoid Avatar
        {
            if (isHuman[i] && isRoot[i]) { selected = i; reason = "Humanoid Avatar on the export root itself"; break; }
        }
        if (selected < 0)
        {
            for (int i = 0; i < candidates.Length; i++)  // 第2優先: それ以外で最初に見つかったHumanoid Avatar(階層走査順)
            {
                if (isHuman[i]) { selected = i; reason = "first candidate with Humanoid Avatar other than export root (hierarchy scan order)"; break; }
            }
        }

        if (selected < 0)
        {
            Debug.LogWarning("D2P: [Humanoid Avatar Select] no Animator with a Humanoid Avatar found"
                + " (" + candidates.Length + " candidate(s), see log above; all have avatar unset or non-Humanoid)");
            return null;
        }

        Debug.Log("D2P: [Humanoid Avatar Select] selected: " + paths[selected] + " (reason: " + reason + ")");
        for (int i = 0; i < candidates.Length; i++)
        {
            if (i == selected) continue;
            Debug.Log("D2P: [Humanoid Avatar Select] not selected: " + paths[i]
                + " (avatarNull=" + avatarNull[i] + " isHuman=" + isHuman[i] + ")");
        }
        return candidates[selected];
    }

    static void ExportHumanoid(GameObject go, string outDir)
    {
        var animator = SelectHumanoidAnimator(go);
        if (animator == null)
            throw new Exception("No Animator with a Humanoid Avatar configuration found");
        var human = new List<HumanBone>(animator.avatar.humanDescription.human);
        ApplyBoneNameSuggestions(go, animator, human, outDir);
        var sb = new StringBuilder();
        sb.Append("{\n  \"format\": \"divetopalworld-humanoid-1\",\n");
        // D2P平坦化済みの印: step01がメッシュ行列=アーマチュア行列の固定を行う
        sb.Append("  \"d2p_flattened\": true,\n");
        // ルートボーン復元のフォールバック用: Hipsのルート基準位置(Unity座標・m)
        var hipsT = animator.GetBoneTransform(HumanBodyBones.Hips);
        if (hipsT != null)
        {
            var p = go.transform.InverseTransformPoint(hipsT.position);
            sb.AppendFormat(System.Globalization.CultureInfo.InvariantCulture,
                "  \"hips_local\": [{0}, {1}, {2}],\n", p.x, p.y, p.z);
        }
        sb.Append("  \"humanoid\": {\n");
        bool first = true;
        foreach (var hb in human)
        {
            if (string.IsNullOrEmpty(hb.boneName)) continue;
            if (!first) sb.Append(",\n");
            first = false;
            sb.AppendFormat("    \"{0}\": \"{1}\"", J(hb.humanName), J(hb.boneName));
        }
        sb.Append("\n  }\n}\n");
        File.WriteAllText(Path.Combine(outDir, "humanoid.json"), sb.ToString(),
            new UTF8Encoding(false));
    }

    // dev#300(実報告VLGQR7ES): Unity純正FBXエクスポータ(com.unity.formats.fbx)は、
    // 書き出し対象の階層内に同名のTransformが複数存在すると、内部で連番サフィックス
    // (例: "Tail"→"Tail_3")を付けて一意化してしまう。ExportHumanoid/ExportMaterialsは
    // このFBXエクスポータ内部のリネームを一切知らず、輸出前のUnity上の名前
    // (Transform.name)をキーにhumanoid.json/material_map.jsonを書くため、輸出対象の
    // 階層に重複名が存在すると、輸出後のFBX実体の名前とズレて参照が外れる
    // (VRM/VRChatアバターの尻尾・耳等のボーンチェーンは同一名の連続が一般的で、
    // その末端に同名の非スキンアクセサリメッシュが付く構成もよくある。
    // ExportMaterials側のseenNamesチェック(重複時に先勝ちで無視)はRenderer同士の
    // 重複しか見ておらず、Renderer名がボーン等の非Renderer Transformと重複する
    // ケースは検知できない――実報告のログに重複警告が出ていなかった事実と整合)。
    //
    // 対策(症状別の特別扱いではなく入口で正規化): 輸出直前にここで階層全体の
    // Transform名を一括して一意化してしまえば、Unity FBXエクスポータが独自に
    // リネームする余地そのものが無くなり、以降の全出力
    // (humanoid.json/統合FBX/material_map.json)が同じ名前で揃う。
    // 呼び出し位置は、これより後に階層(GameObject/Transform)を追加・改名する
    // 処理を置かないこと(置くと再びズレが復活する)。
    static void EnsureUniqueTransformNames(GameObject root)
    {
        var all = new List<Transform>();
        CollectAllTransforms(root.transform, all);
        var names = new List<string>(all.Count);
        foreach (var t in all) names.Add(t.name);
        var uniqueNames = ResolveUniqueNames(names);
        int renamed = 0;
        for (int i = 0; i < all.Count; i++)
        {
            if (uniqueNames[i] == names[i]) continue;
            Debug.Log("D2P: [DupNameResolve] " + GetHierarchyPath(all[i]) + " -> \"" + uniqueNames[i] + "\"");
            all[i].name = uniqueNames[i];
            renamed++;
        }
        if (renamed > 0)
            Debug.Log("D2P: DupNameResolve complete, renamed " + renamed + " (uniquified export hierarchy names)");
    }

    // D2P_UNIQUENAME_PURE_BEGIN
    // 名前列(輸出階層をたどった順)の重複を解消し、全体で一意な名前列を返す
    // 純粋関数。UnityEngine型に一切依存しない(文字列・コレクションのみ)ため、
    // Unity無しでdotnet単体でも振る舞いを検証できる
    // (tests\unity_exporter\test_material_map_dup_rename.py参照)。
    // 初出の名前はそのまま、2回目以降は "_2", "_3", ... を付けて一意化する。
    // 付与候補が既存の名前(元から"_2"等が使われているケースを含む)と衝突する
    // 場合はさらに数字を進めて衝突しない名前を探す(値を寄せて合わせる場当たり
    // 実装にしない――既存の"Tail_2"を上書きしてしまうような実装は不可)。
    internal static List<string> ResolveUniqueNames(List<string> namesInOrder)
    {
        var used = new HashSet<string>();
        var result = new List<string>(namesInOrder.Count);
        foreach (var original in namesInOrder)
        {
            string candidate = original;
            if (!used.Add(candidate))
            {
                int n = 1;
                do
                {
                    n++;
                    candidate = original + "_" + n;
                } while (!used.Add(candidate));
            }
            result.Add(candidate);
        }
        return result;
    }
    // D2P_UNIQUENAME_PURE_END

    // D2P_SECONDALBEDO_PURE_BEGIN
    // dev#30残タスク(2枚目テクスチャ/デカール層のケース)の検出ロジック。
    // 現行パイプラインはメインテクスチャ1枚しか焼き込まない(alpha_mode/
    // base_color/textureのみをmaterial_map.json→avatar_meta.jsonへ運ぶ)ため、
    // 頬染め等が「2枚目アルベドテクスチャ」レイヤーで表現されている場合、
    // 焼き込みは行われず黙って消える(issue dev#30本文の仮説どおり)。
    // ここでは焼き込みは実装せず、検出結果を material_map.json へ計測
    // フィールドとして出すところまでに留める(オーナー裁定: 焼き込み実装は
    // 別途R&D、対応にはPhase 2級のリスク評価が要る)。
    //
    // 特定シェーダー名を決め打ちせず、プロパティの存在(HasProperty)+有効
    // フラグの値だけで判定する(CLAUDE.md「入口で正規化、特別扱いを積むな」
    // 節。既存コードの"_Cull"読み取りと同じ流儀)。UnityEngine型に一切
    // 依存しない純粋関数なのでUnity無しでdotnet単体でも検証できる
    // (tests\unity_exporter\test_second_albedo_detection.py参照)。
    internal static bool DetectSecondAlbedoLayer(
        bool hasMain2nd, float useMain2nd, bool hasMain3rd, float useMain3rd)
    {
        if (hasMain2nd && useMain2nd > 0.5f) return true;
        if (hasMain3rd && useMain3rd > 0.5f) return true;
        return false;
    }
    // D2P_SECONDALBEDO_PURE_END

    static void ExportMaterials(GameObject go, string outDir, string fbxName)
    {
        var texFiles = new Dictionary<Texture, string>();
        var sb = new StringBuilder();
        sb.Append("{\n  \"format\": \"divetopalworld-materials-1\",\n");
        sb.AppendFormat("  \"fbx\": \"{0}\",\n  \"meshes\": {{\n", J(fbxName));
        bool firstMesh = true;
        // SkinnedMeshRenderer(体・服等スキン済み)に加え、MeshRenderer(帽子・
        // リボン等、ボーンへTransform直付けの非スキンアクセサリ。PhysBone/
        // Constraintで動かす構成でVRChatアバターにごく一般的)も走査対象に
        // 含める。従来SkinnedMeshRendererのみだったため、非スキンメッシュは
        // material_map.jsonに載らず、step01_import_vrm.pyの
        // extract_materials_from_unity_map()が単色フォールバックにしていた
        // (2026-07-26実測: shapell_Osakiのベレー帽・リボンが灰色化)。
        // 出力名はどちらもRenderer.name(=GameObject名)で揃える。Blender側は
        // orig_names(FBXインポート時の元オブジェクト名)をキーに
        // mesh_map.get(orig)で引くため、SkinnedMeshRendererと同じ命名規則で
        // 揃える必要がある。
        var seenNames = new HashSet<string>();
        var renderers = new List<Renderer>();
        renderers.AddRange(go.GetComponentsInChildren<SkinnedMeshRenderer>(false));
        renderers.AddRange(go.GetComponentsInChildren<MeshRenderer>(false));
        foreach (var r in renderers)
        {
            Mesh sharedMesh;
            var smr = r as SkinnedMeshRenderer;
            if (smr != null)
                sharedMesh = smr.sharedMesh;
            else
            {
                var mf = r.GetComponent<MeshFilter>();
                sharedMesh = mf != null ? mf.sharedMesh : null;
            }
            if (sharedMesh == null || !r.enabled) continue;
            if (!seenNames.Add(r.name))
            {
                Debug.LogWarning("D2P: duplicate mesh name in material_map.json: " + r.name
                                  + " (ignored, first wins)");
                continue;
            }
            if (!firstMesh) sb.Append(",\n");
            firstMesh = false;
            sb.AppendFormat("    \"{0}\": [\n", J(r.name));
            var mats = r.sharedMaterials;
            for (int i = 0; i < mats.Length; i++)
            {
                var m = mats[i];
                string tex = null;
                float[] col = { 1, 1, 1, 1 };
                bool twoSided = false;
                bool secondAlbedo = false;
                string matName = m != null ? m.name : "";
                if (m != null)
                {
                    if (m.mainTexture != null)
                        tex = SaveTexture(m.mainTexture, outDir, texFiles, matName);
                    if (m.HasProperty("_Color"))
                    {
                        var c = m.color;
                        col = new[] { c.r, c.g, c.b, c.a };
                    }
                    // lilToon等: _Cull 0=両面
                    if (m.HasProperty("_Cull"))
                        twoSided = m.GetFloat("_Cull") < 0.5f;
                    // dev#30残タスク: 2枚目/3枚目アルベドテクスチャ(lilToonの
                    // Main2nd/Main3rd等)が有効化されているかの検出のみ(焼き込みはしない)
                    bool hasMain2nd = m.HasProperty("_UseMain2ndTex");
                    float useMain2nd = hasMain2nd ? m.GetFloat("_UseMain2ndTex") : 0f;
                    bool hasMain3rd = m.HasProperty("_UseMain3rdTex");
                    float useMain3rd = hasMain3rd ? m.GetFloat("_UseMain3rdTex") : 0f;
                    secondAlbedo = DetectSecondAlbedoLayer(hasMain2nd, useMain2nd, hasMain3rd, useMain3rd);
                }
                sb.AppendFormat(
                    "      {{\"material_name\": \"{0}\", \"texture\": {1}, " +
                    "\"color\": [{2}], \"double_sided\": {3}, " +
                    "\"second_albedo_detected\": {5}}}{4}\n",
                    J(matName),
                    tex == null ? "null" : "\"" + J(tex) + "\"",
                    string.Join(", ", Array.ConvertAll(col,
                        v => v.ToString(System.Globalization.CultureInfo.InvariantCulture))),
                    twoSided ? "true" : "false",
                    i < mats.Length - 1 ? "," : "",
                    secondAlbedo ? "true" : "false");
            }
            sb.Append("    ]");
        }
        sb.Append("\n  }\n}\n");
        File.WriteAllText(Path.Combine(outDir, "material_map.json"), sb.ToString(),
            new UTF8Encoding(false));
    }

    // dev#1168(2026-08-09、ラボ機能「シェイプキー」): prefab経路のGUIが
    // 「どのメッシュにどんなシェイプキー(ブレンドシェイプ)があるか」を
    // Unity/Blenderを起動せずに一覧できるよう、material_map.jsonと同じ流儀の
    // サイドカーJSONを書き出す。対象はExportMaterials()と同じRenderer走査
    // (SkinnedMeshRenderer、有効なもののみ)だが、非スキンMeshRenderer側は
    // ブレンドシェイプを持ち得ないため対象外。出力名はRenderer.name(=
    // material_map.jsonと同じ命名規則、Blender側のorig_names逆引きで一致させる
    // 前提、app_py\ui\shapekey_select_dialog.py参照)。ブレンドシェイプを
    // 1つも持たないメッシュはJSONへ含めない(空エントリを避ける)。
    static void ExportShapeKeys(GameObject go, string outDir, string fbxName)
    {
        var sb = new StringBuilder();
        sb.Append("{\n  \"format\": \"divetopalworld-shapekeys-1\",\n");
        sb.AppendFormat("  \"fbx\": \"{0}\",\n  \"meshes\": {{\n", J(fbxName));
        bool first = true;
        var seenNames = new HashSet<string>();
        foreach (var r in go.GetComponentsInChildren<SkinnedMeshRenderer>(false))
        {
            var mesh = r.sharedMesh;
            if (mesh == null || !r.enabled || mesh.blendShapeCount == 0) continue;
            if (!seenNames.Add(r.name)) continue;  // material_map.jsonと同じ先勝ち
            if (!first) sb.Append(",\n");
            first = false;
            sb.AppendFormat("    \"{0}\": [\n", J(r.name));
            for (int s = 0; s < mesh.blendShapeCount; s++)
            {
                sb.AppendFormat("      \"{0}\"{1}\n",
                    J(mesh.GetBlendShapeName(s)), s < mesh.blendShapeCount - 1 ? "," : "");
            }
            sb.Append("    ]");
        }
        sb.Append("\n  }\n}\n");
        File.WriteAllText(Path.Combine(outDir, "shape_keys.json"), sb.ToString(),
            new UTF8Encoding(false));
    }

    // dev#1277(2026-08-09、ラボ機能「ボーンでメッシュ削除」の選択式化):
    // prefab経路のGUIが「このアバターにどんなボーンがあるか」をUnity/Blenderを
    // 起動せずに一覧できるよう、shape_keys.jsonと同じ流儀のサイドカーJSONを
    // 書き出す。対象はEnsureUniqueTransformNames()と同じ輸出階層の全Transform
    // (CollectAllTransforms()の再利用、DESIGN.md 3.2節)——アーマチュアの
    // ボーンだけに絞り込まない。理由: 装飾用の末端メッシュTransform等が
    // 数件混じっても実害は無い(Blender側drop_bone_meshes()の
    // `arm.data.bones.get(name)`は実在するボーン名としか一致せず、非ボーン名は
    // 選択してもno-opになるだけ、DESIGN.md 3.2節「わからないときは黙って
    // 壊さない」設計)。呼び出し位置はEnsureUniqueTransformNames()より後
    // (=名前が最終形に確定した後)である必要がある。
    static void ExportBones(GameObject go, string outDir, string fbxName)
    {
        var all = new List<Transform>();
        CollectAllTransforms(go.transform, all);
        var sb = new StringBuilder();
        sb.Append("{\n  \"format\": \"divetopalworld-bones-1\",\n");
        sb.AppendFormat("  \"fbx\": \"{0}\",\n  \"bones\": [\n", J(fbxName));
        var seenNames = new HashSet<string>();
        bool first = true;
        foreach (var t in all)
        {
            if (!seenNames.Add(t.name)) continue;  // material_map.json等と同じ先勝ち(重複は無いはずだが念のため)
            if (!first) sb.Append(",\n");
            first = false;
            sb.AppendFormat("    \"{0}\"", J(t.name));
        }
        sb.Append("\n  ]\n}\n");
        File.WriteAllText(Path.Combine(outDir, "bones.json"), sb.ToString(),
            new UTF8Encoding(false));
    }

    // dev#1356(揺れもの、dev#19「両路線共通の入力基盤」): prefab経路のVRCPhysBone
    // コンポーネントは、StripNonWhitelistedPreBake第1段(IsWhitelistedComponentType
    // が"VRC."名前空間を許可)では除去されないが、輸出直前のStripNonEssentialPostBake
    // (必須5型のみ許可)で必ず消える——bones.json/shape_keys.jsonと同じ「消える前に
    // サイドカーへ抽出する」パターンをPhysBoneにも適用する。
    //
    // VRC SDKへのコンパイル時参照は追加しない(オーナー裁定「VRC SDKには一切触れない」
    // 2026-07-29 dev#116/#117、SDKの実行・ビルドフック呼び出し・成果物解析が禁止対象)。
    // FindType()による型名文字列の動的解決のみを使い、シーンに既に存在する
    // コンポーネントのTransform階層を読むだけ(SDKの実行やビルドフック呼び出しは
    // 一切行わない)。オーナー裁定(2026-08-11、dev#19記録)「PhysBoneコンポーネント
    // 走査OK(グレーだが既存vrc→vrm変換ツールもやっている)。SDK実行・ビルドフックでなく
    // prefab上のコンポーネントデータ読み取りのみ」によりこの走査自体は許可されている。
    // VRC SDK未導入のプロジェクトではFindTypeがnullを返し、空の"physbones": []を書いて
    // 正常終了する(bones.json等と同じ「無ければ空」の安全側フォールバック)。
    //
    // 意味論(オーナー裁定2026-08-11、work\rd_19_r1_wall\PROPOSAL.md「壁(a)」):
    // 「搭載(アンカー)ボーン自身は揺れない、子から揺れる」。1件のVRCPhysBoneにつき
    // "anchor"(rootTransform未設定ならPhysBoneが乗っているTransform自身)+
    // "chains"(anchorの各子孫リーフまでのボーン名列、anchor自身は含まない)を書く。
    // 複数の子孫リーフ=マルチルート/分岐チェーンは複数chainsとして全列挙する
    // (1本道の途中で分岐したらそこから先だけを別チェーンにするのではなく、
    // 「anchorの子から各リーフまでの経路」を単純に全列挙する最小実装——分岐点より
    // 手前の共有区間が複数チェーンに重複して現れるが、意味論(どのボーンが
    // どのリーフの揺れに寄与するか)は保持される。より精緻な分岐点分割は
    // 消費側(写像への結線、別WP)が必要になった時点で再検討する)。
    // anchorに子孫が1つも無い(=何も揺れない)PhysBoneはエントリごと省略する
    // (ExportShapeKeysの「空エントリを避ける」流儀と同じ)。
    // 呼び出し位置はStripNonEssentialPostBakeの直前(PhysBoneがまだ生きている
    // 最後のタイミング)かつEnsureUniqueTransformNamesの直後(輸出される最終名で
    // 一致させるため、bones.json/shape_keys.jsonと同じ制約)であること。
    //
    // dev#1508 W1a(2026-08-16、work\sway_pbunit_design\DESIGN.md §1): 「揺れもの一覧」
    // をPB/SBコンポーネント単位で語れるようにするための拡張。追加フィールド:
    //   - "anchor_explicit_root": rootTransformが明示設定されていたか(comp.transformと
    //     異なるか)。SPEC.md §5「PBコンポーネントはボーン上にあるとは限らない」の
    //     区別に使う。
    //   - "pb_object_name"/"pb_object_path": PhysBoneコンポーネント自身が載っている
    //     GameObjectの表示名と、輸出ルートからのヒエラルキーパス(GetHierarchyPath()
    //     を再利用)。"anchor"(効果対象・rootTransform解決後)とは別概念
    //     (flatapronの実例: PBはDynamic/apronという別Objectに乗り、rootTransformで
    //     骨を指す。SPEC.md §5)。
    //   - params.integration_type / ignore_transforms / endpoint_position /
    //     multi_child_type: いずれもVRCPhysBoneBaseの実フィールド(integrationType/
    //     ignoreTransforms/endpointPosition/multiChildType)をリフレクションで読む。
    //     フィールド名は本WPで新規に確認済み(scratchpad\pbrefl\Program.cs、
    //     C:\UnityP\OOsakiのVRC.Dynamics.dllを通常のAssembly.LoadFromでロードし
    //     リフレクションのみで型・フィールドを列挙——コンポーネントのインスタンス化や
    //     Update/シミュレーション実行は一切行っていない静的読み取り、既存の
    //     pb_param_export WPと同じ精神)。
    //   - params.colliders: このPhysBoneが参照するVRCPhysBoneColliderBaseの一覧を、
    //     下記コライダー全列挙(トップレベル"colliders")のキーで指す参照のみ
    //     (SPEC.md §2「コライダー放棄確定」のとおりコピー実装はしない、診断用)。
    // トップレベル"colliders": シーン全体(輸出階層go配下)のVRCPhysBoneColliderを
    // 別セクションで全列挙する(SPEC.md §5「コライダー(球/カプセル/平面・位置・
    // サイズ)も別セクションで全列挙」)。PB列挙と同じくactiveness非依存・
    // GetComponentsInChildrenで走査する。
    static void ExtractPhysBoneChains(GameObject go, string outDir)
    {
        var sb = new StringBuilder();
        var entries = new List<string>();
        var colliderEntries = new List<string>();

        var physBoneType = FindType("VRC.SDK3.Dynamics.PhysBone.Components.VRCPhysBone");
        var physBoneColliderType = FindType("VRC.SDK3.Dynamics.PhysBone.Components.VRCPhysBoneCollider");
        if (physBoneType == null)
        {
            Debug.Log("D2P: VRCPhysBone type not found (VRC SDK not installed); writing empty physbones.json");
        }
        else
        {
            const BindingFlags F = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
            var rootField = physBoneType.GetField("rootTransform", F);
            // dev#19(揺れもの)/pb_param_export WP: PhysBoneの数値・角度制限パラメータ。
            // フィールド名はVRC SDKの型を直接参照せず(VRC SDKには一切触れない裁定
            // dev#117のため)、既存のrootTransform同様リフレクションのみで読む。
            // 実在するフィールド名は、C:\UnityP\test22のVRC.Dynamics.dll(実機に
            // 導入済みのVRC SDK本体)をSystem.Reflection.Metadataでメタデータのみ
            // 読み取り(型のロード・実行は一切していない)して確認済み——
            // VRC.Dynamics.VRCPhysBoneBase(VRCPhysBoneの基底クラス)がpublicの
            // インスタンスフィールドとして持つ: pull/spring/stiffness/gravity/
            // gravityFalloff/immobile/immobileType(enum AllMotion|World)/
            // limitType(enum None|Angle|Hinge|Polar)/maxAngleX/maxAngleZ/
            // limitRotation(Vector3)/radius。**「damping」という名のフィールドは
            // 存在しない**(指示書原文の想定と異なる。値を寄せず正直に書く:
            // damping相当の概念に一番近いのはgravity/gravityFalloff/spring
            // で、いずれも別キーとして下記に含めている。damping自体は出力しない)。
            // 万一SDKバージョン差でフィールドが見つからない場合は各GetFieldが
            // nullを返し、下記ParamsJson()がnullで正直に出力する(推測補完しない)。
            var pullField = physBoneType.GetField("pull", F);
            var springField = physBoneType.GetField("spring", F);
            var stiffnessField = physBoneType.GetField("stiffness", F);
            var gravityField = physBoneType.GetField("gravity", F);
            var gravityFalloffField = physBoneType.GetField("gravityFalloff", F);
            var immobileField = physBoneType.GetField("immobile", F);
            var immobileTypeField = physBoneType.GetField("immobileType", F);
            var limitTypeField = physBoneType.GetField("limitType", F);
            var maxAngleXField = physBoneType.GetField("maxAngleX", F);
            var maxAngleZField = physBoneType.GetField("maxAngleZ", F);
            var limitRotationField = physBoneType.GetField("limitRotation", F);
            var radiusField = physBoneType.GetField("radius", F);
            // dev#1508 W1a追加分(field名確認の記録は上のクラスコメント参照)
            var integrationTypeField = physBoneType.GetField("integrationType", F);
            var ignoreTransformsField = physBoneType.GetField("ignoreTransforms", F);
            var endpointPositionField = physBoneType.GetField("endpointPosition", F);
            var multiChildTypeField = physBoneType.GetField("multiChildType", F);
            var collidersField = physBoneType.GetField("colliders", F);

            FieldInfo colliderRootField = null, colliderShapeTypeField = null,
                colliderRadiusField = null, colliderHeightField = null,
                colliderPositionField = null, colliderRotationField = null;
            if (physBoneColliderType != null)
            {
                colliderRootField = physBoneColliderType.GetField("rootTransform", F);
                colliderShapeTypeField = physBoneColliderType.GetField("shapeType", F);
                colliderRadiusField = physBoneColliderType.GetField("radius", F);
                colliderHeightField = physBoneColliderType.GetField("height", F);
                colliderPositionField = physBoneColliderType.GetField("position", F);
                colliderRotationField = physBoneColliderType.GetField("rotation", F);
            }

            // トップレベル"colliders"の全列挙 + PB側の参照解決用キーマップ構築。
            // キーはコライダーが載っているGameObjectのヒエラルキーパス
            // (GetHierarchyPathはTransform階層で常に一意なため、同一Transform上に
            // 複数コライダーが乗る縮退ケースのみ"#2"等のsuffixで衝突回避する)。
            var colliderKeys = new Dictionary<Component, string>();
            if (physBoneColliderType != null)
            {
                var colliderComps = go.GetComponentsInChildren(physBoneColliderType, true);
                var usedKeys = new HashSet<string>();
                foreach (var cc in colliderComps)
                {
                    var colComp = cc as Component;
                    if (colComp == null) continue;
                    string basePath = GetHierarchyPath(colComp.transform);
                    string key = basePath;
                    int suffix = 2;
                    while (!usedKeys.Add(key)) key = basePath + "#" + (suffix++);
                    colliderKeys[colComp] = key;

                    Transform colliderAnchor = colComp.transform;
                    bool colliderExplicitRoot = false;
                    if (colliderRootField != null)
                    {
                        var rt = colliderRootField.GetValue(colComp) as Transform;
                        if (rt != null) { colliderAnchor = rt; colliderExplicitRoot = true; }
                    }

                    var ce = new StringBuilder();
                    ce.Append("    {\n");
                    ce.AppendFormat("      \"key\": \"{0}\",\n", J(key));
                    ce.AppendFormat("      \"name\": \"{0}\",\n", J(colComp.gameObject.name));
                    ce.AppendFormat("      \"path\": \"{0}\",\n", J(basePath));
                    ce.AppendFormat("      \"anchor\": \"{0}\",\n", J(colliderAnchor.name));
                    ce.AppendFormat("      \"anchor_explicit_root\": {0},\n", colliderExplicitRoot ? "true" : "false");
                    ce.AppendFormat("      \"shape_type\": {0},\n", EnumFieldJson(colliderShapeTypeField, colComp));
                    ce.AppendFormat("      \"radius\": {0},\n", FloatFieldJson(colliderRadiusField, colComp));
                    ce.AppendFormat("      \"height\": {0},\n", FloatFieldJson(colliderHeightField, colComp));
                    ce.AppendFormat("      \"position\": {0},\n", Vector3FieldJson(colliderPositionField, colComp));
                    ce.AppendFormat("      \"rotation\": {0}\n", QuaternionFieldJson(colliderRotationField, colComp));
                    ce.Append("    }");
                    colliderEntries.Add(ce.ToString());
                }
                Debug.Log("D2P: ExtractPhysBoneChains found " + colliderComps.Length + " VRCPhysBoneCollider component(s)");
            }
            else
            {
                Debug.Log("D2P: VRCPhysBoneCollider type not found; writing empty colliders section");
            }

            var comps = go.GetComponentsInChildren(physBoneType, true);  // bones.json同様、activeness非依存(輸出階層に残るTransformを取りこぼさない)
            int skipped = 0;
            foreach (var c in comps)
            {
                var comp = c as Component;
                if (comp == null) continue;
                Transform anchor = comp.transform;
                var explicitRoot = rootField != null ? rootField.GetValue(comp) as Transform : null;
                bool anchorExplicitRoot = explicitRoot != null;
                if (explicitRoot != null) anchor = explicitRoot;

                // dev#1508(ゴミ骨鎖二重化修正、night_20260817 laneB): 単純に
                // Transform階層を総なめするだけでは、Merge Armatureが服armature
                // 側の非マッチ骨(例: 服だけに残った耳骨Head_L.003)を親骨(共有
                // されるHead_L.002)の子として再親化したものまで「鎖の一部」として
                // 拾ってしまい、本来1本のはずの鎖が2本(実鎖+ゴミ鎖)に分岐する
                // (実測: work\wp_wfinal_run5\comodo_export\physbones.json)。
                // VRCPhysBoneBase.ignoreTransforms(既にignoreTransformsFieldで
                // リフレクション読み取り済み)は、Modular AvatarのMergeArmatureHook
                // (`src.name = src.name + "$" + Guid.NewGuid()`でマングルした
                // 非マッチ骨に`ModularAvatarPBBlocker`を付与)→PhysboneBlockerPass
                // (そのTransformを祖先の全PhysBoneのignoreTransformsへ自動追加)
                // という既存のMA機構により、**MA自身が「これは物理演算対象外」と
                // 判定した結果が既に入っている**(実測でHead_L.001のignore_transforms
                // に"Head_L.003$<guid>"が入っていることを確認済み)。これを鎖の
                // 木構造の枝刈りに使うことで、閾値・座標のマジックナンバー無しに
                // VRChat実機の実際のゆれ挙動(ignoreTransforms指定Transform以下は
                // サブツリーごと物理演算から除外される)と一致させる。
                // 却下した代替案: 「頂点ウェイトの有無」で判定する案は、Blender
                // headlessで実FBXを検査した結果、本物の耳先端骨(Head_L.002_end)
                // 自体も頂点ウェイトゼロ(位置マーカーのみ)であることが判明し、
                // ゴミ骨と区別できないため反証済み(PROGRESS.md参照)。
                var ignoreNames = new HashSet<string>();
                if (ignoreTransformsField != null)
                {
                    var rawIgnore = ignoreTransformsField.GetValue(comp) as System.Collections.IEnumerable;
                    if (rawIgnore != null)
                        foreach (var item in rawIgnore)
                        {
                            var it = item as Transform;
                            if (it != null) ignoreNames.Add(it.name);
                        }
                }
                var childrenByName = BuildChildrenByNameMap(anchor);
                var chains = BuildPhysBoneLeafChains(anchor.name, childrenByName, ignoreNames);
                if (chains.Count == 0)
                {
                    skipped++;
                    continue;  // 何も揺れないPhysBone(anchorが末端)はエントリを書かない
                }

                var chainSb = new StringBuilder();
                chainSb.Append("    {\n");
                chainSb.AppendFormat("      \"anchor\": \"{0}\",\n", J(anchor.name));
                chainSb.AppendFormat("      \"anchor_explicit_root\": {0},\n", anchorExplicitRoot ? "true" : "false");
                chainSb.AppendFormat("      \"pb_object_name\": \"{0}\",\n", J(comp.gameObject.name));
                chainSb.AppendFormat("      \"pb_object_path\": \"{0}\",\n", J(GetHierarchyPath(comp.transform)));
                chainSb.Append("      \"chains\": [\n");
                for (int ci = 0; ci < chains.Count; ci++)
                {
                    chainSb.Append("        [");
                    for (int ni = 0; ni < chains[ci].Count; ni++)
                    {
                        chainSb.AppendFormat("\"{0}\"{1}", J(chains[ci][ni]),
                            ni < chains[ci].Count - 1 ? ", " : "");
                    }
                    chainSb.Append(ci < chains.Count - 1 ? "],\n" : "]\n");
                }
                chainSb.Append("      ],\n      \"params\": ");
                chainSb.Append(PhysBoneParamsJson(comp,
                    pullField, springField, stiffnessField, gravityField, gravityFalloffField,
                    immobileField, immobileTypeField, limitTypeField, maxAngleXField, maxAngleZField,
                    limitRotationField, radiusField,
                    integrationTypeField, ignoreTransformsField, endpointPositionField, multiChildTypeField,
                    collidersField, colliderKeys));
                chainSb.Append("\n    }");
                entries.Add(chainSb.ToString());
            }
            Debug.Log("D2P: ExtractPhysBoneChains found " + comps.Length + " VRCPhysBone component(s), "
                       + entries.Count + " with chains, " + skipped + " skipped (no descendants)");
        }

        sb.Append("{\n  \"format\": \"divetopalworld-physbones-1\",\n  \"physbones\": [\n");
        sb.Append(string.Join(",\n", entries));
        sb.Append("\n  ],\n  \"colliders\": [\n");
        sb.Append(string.Join(",\n", colliderEntries));
        sb.Append("\n  ]\n}\n");
        File.WriteAllText(Path.Combine(outDir, "physbones.json"), sb.ToString(),
            new UTF8Encoding(false));
    }

    // ExtractPhysBoneChainsのヘルパー: 1つのVRCPhysBoneコンポーネントから、
    // 数値・角度制限パラメータをJSONオブジェクト文字列へ整形する。各フィールドは
    // FieldInfoがnull(=このSDKバージョンに存在しない)、またはGetValueが返す値の
    // 型が想定と異なる場合、推測せずJSON null を出力する。
    // dev#1508 W1a: integration_type/ignore_transforms/endpoint_position/
    // multi_child_type/collidersを追加(DESIGN.md §1.2)。collidersFieldは
    // colliderKeysマップ(ExtractPhysBoneChains側で構築、コンポーネント→トップレベル
    // "colliders"セクションのキー)を使って参照解決する(コピーではなく参照のみ、
    // SPEC.md §2「コライダー放棄確定」)。
    static string PhysBoneParamsJson(Component comp,
        FieldInfo pullField, FieldInfo springField, FieldInfo stiffnessField,
        FieldInfo gravityField, FieldInfo gravityFalloffField,
        FieldInfo immobileField, FieldInfo immobileTypeField,
        FieldInfo limitTypeField, FieldInfo maxAngleXField, FieldInfo maxAngleZField,
        FieldInfo limitRotationField, FieldInfo radiusField,
        FieldInfo integrationTypeField, FieldInfo ignoreTransformsField,
        FieldInfo endpointPositionField, FieldInfo multiChildTypeField,
        FieldInfo collidersField, Dictionary<Component, string> colliderKeys)
    {
        var p = new StringBuilder();
        p.Append("{\n");
        p.AppendFormat("        \"pull\": {0},\n", FloatFieldJson(pullField, comp));
        p.AppendFormat("        \"spring\": {0},\n", FloatFieldJson(springField, comp));
        p.AppendFormat("        \"stiffness\": {0},\n", FloatFieldJson(stiffnessField, comp));
        p.AppendFormat("        \"gravity\": {0},\n", FloatFieldJson(gravityField, comp));
        p.AppendFormat("        \"gravity_falloff\": {0},\n", FloatFieldJson(gravityFalloffField, comp));
        p.AppendFormat("        \"immobile\": {0},\n", FloatFieldJson(immobileField, comp));
        p.AppendFormat("        \"immobile_type\": {0},\n", EnumFieldJson(immobileTypeField, comp));
        p.AppendFormat("        \"limit_type\": {0},\n", EnumFieldJson(limitTypeField, comp));
        p.AppendFormat("        \"max_angle_x\": {0},\n", FloatFieldJson(maxAngleXField, comp));
        p.AppendFormat("        \"max_angle_z\": {0},\n", FloatFieldJson(maxAngleZField, comp));
        p.AppendFormat("        \"limit_rotation\": {0},\n", Vector3FieldJson(limitRotationField, comp));
        p.AppendFormat("        \"radius\": {0},\n", FloatFieldJson(radiusField, comp));
        p.AppendFormat("        \"integration_type\": {0},\n", EnumFieldJson(integrationTypeField, comp));
        p.AppendFormat("        \"ignore_transforms\": {0},\n", TransformNameListFieldJson(ignoreTransformsField, comp));
        p.AppendFormat("        \"endpoint_position\": {0},\n", Vector3FieldJson(endpointPositionField, comp));
        p.AppendFormat("        \"multi_child_type\": {0},\n", EnumFieldJson(multiChildTypeField, comp));
        p.AppendFormat("        \"colliders\": {0}\n", ColliderRefsJson(collidersField, comp, colliderKeys));
        p.Append("      }");
        return p.ToString();
    }

    static string FloatFieldJson(FieldInfo field, Component comp)
    {
        if (field == null) return "null";
        object raw;
        try { raw = field.GetValue(comp); }
        catch { return "null"; }
        if (raw is float f)
            return f.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
        return "null";
    }

    // enumのVRC SDK型を直接参照せず(SDK非依存の裁定のため)、boxed objectの
    // ToString()で名前を取る(既存のPhysBoneMigrationチェック等と同じくSDK型
    // 非参照のまま値の意味を読む手法)。
    static string EnumFieldJson(FieldInfo field, Component comp)
    {
        if (field == null) return "null";
        object raw;
        try { raw = field.GetValue(comp); }
        catch { return "null"; }
        if (raw == null) return "null";
        return "\"" + J(raw.ToString()) + "\"";
    }

    static string Vector3FieldJson(FieldInfo field, Component comp)
    {
        if (field == null) return "null";
        object raw;
        try { raw = field.GetValue(comp); }
        catch { return "null"; }
        if (raw is Vector3 v)
        {
            return string.Format(System.Globalization.CultureInfo.InvariantCulture,
                "[{0}, {1}, {2}]",
                v.x.ToString("R", System.Globalization.CultureInfo.InvariantCulture),
                v.y.ToString("R", System.Globalization.CultureInfo.InvariantCulture),
                v.z.ToString("R", System.Globalization.CultureInfo.InvariantCulture));
        }
        return "null";
    }

    // dev#1508 W1a: VRCPhysBoneColliderBase.rotation(Quaternion)用。x/y/z/wの
    // 4要素配列として出力する(オイラー角への変換は情報量が落ちるため避ける)。
    static string QuaternionFieldJson(FieldInfo field, Component comp)
    {
        if (field == null) return "null";
        object raw;
        try { raw = field.GetValue(comp); }
        catch { return "null"; }
        if (raw is Quaternion q)
        {
            return string.Format(System.Globalization.CultureInfo.InvariantCulture,
                "[{0}, {1}, {2}, {3}]",
                q.x.ToString("R", System.Globalization.CultureInfo.InvariantCulture),
                q.y.ToString("R", System.Globalization.CultureInfo.InvariantCulture),
                q.z.ToString("R", System.Globalization.CultureInfo.InvariantCulture),
                q.w.ToString("R", System.Globalization.CultureInfo.InvariantCulture));
        }
        return "null";
    }

    // dev#1508 W1a: VRCPhysBoneBase.ignoreTransforms(List<Transform>)用。
    // EnsureUniqueTransformNames()が輸出直前に名前重複を解消済みのため、
    // "anchor"/"chains"と同じくボーンの生名(パスではない)で足りる。
    static string TransformNameListFieldJson(FieldInfo field, Component comp)
    {
        if (field == null) return "[]";
        object raw;
        try { raw = field.GetValue(comp); }
        catch { return "[]"; }
        var list = raw as System.Collections.IEnumerable;
        if (list == null) return "[]";
        var names = new List<string>();
        foreach (var item in list)
        {
            var t = item as Transform;
            if (t != null) names.Add(t.name);
        }
        var sb = new StringBuilder("[");
        for (int i = 0; i < names.Count; i++)
            sb.AppendFormat("\"{0}\"{1}", J(names[i]), i < names.Count - 1 ? ", " : "");
        sb.Append("]");
        return sb.ToString();
    }

    // dev#1508 W1a: VRCPhysBoneBase.colliders(List<VRCPhysBoneColliderBase>)用。
    // コピーではなく、トップレベル"colliders"セクションのキーへの参照のみを書く
    // (SPEC.md §2「コライダー放棄確定」、診断用途)。colliderKeysに無い場合
    // (輸出階層外の参照等、通常は起きないはずの縮退ケース)はその場でパスを
    // 計算してフォールバックする(黙って握りつぶさない)。
    static string ColliderRefsJson(FieldInfo field, Component comp, Dictionary<Component, string> colliderKeys)
    {
        if (field == null) return "[]";
        object raw;
        try { raw = field.GetValue(comp); }
        catch { return "[]"; }
        var list = raw as System.Collections.IEnumerable;
        if (list == null) return "[]";
        var keys = new List<string>();
        foreach (var item in list)
        {
            var c = item as Component;
            if (c == null) continue;
            string key;
            if (colliderKeys != null && colliderKeys.TryGetValue(c, out key))
                keys.Add(key);
            else
                keys.Add(GetHierarchyPath(c.transform));
        }
        var sb = new StringBuilder("[");
        for (int i = 0; i < keys.Count; i++)
            sb.AppendFormat("\"{0}\"{1}", J(keys[i]), i < keys.Count - 1 ? ", " : "");
        sb.Append("]");
        return sb.ToString();
    }

    // ExtractPhysBoneChainsのヘルパー: anchor(Transform)配下の全階層を
    // 「名前→直接の子の名前リスト」の隣接マップへ変換する薄いアダプタ。
    // ExtractPhysBoneChainsはEnsureUniqueTransformNames()実行後に呼ばれるため、
    // この時点で輸出階層全体のTransform名は既に一意(重複ゼロ)であることが
    // 保証されており、Transform識別子の代わりに名前をキーに使っても安全。
    static Dictionary<string, List<string>> BuildChildrenByNameMap(Transform anchor)
    {
        var map = new Dictionary<string, List<string>>();
        var stack = new Stack<Transform>();
        stack.Push(anchor);
        while (stack.Count > 0)
        {
            var t = stack.Pop();
            var kids = new List<string>();
            foreach (Transform c in t)
            {
                kids.Add(c.name);
                stack.Push(c);
            }
            map[t.name] = kids;
        }
        return map;
    }

    // D2P_PBCHAIN_PURE_BEGIN
    // dev#1508(ゴミ骨鎖二重化修正、night_20260817 laneB): PhysBoneの子孫木を
    // 「名前→直接の子の名前リスト」の隣接マップ(childrenByName)として受け取り、
    // ignoreNames(VRCPhysBoneBase.ignoreTransformsから得た名前集合)に含まれる
    // ノードとその部分木全体を除外した上で、anchorNameの子から辿れるリーフ
    // チェーンの一覧を返す純粋関数。UnityEngine型に一切依存しない(文字列・
    // コレクションのみ)ため、dotnet単体で振る舞いを検証できる
    // (tests\unity_exporter\test_physbone_chain_ignore_dev1508.py参照)。
    // ignoreNamesによる除外は「そのノード自身と子孫全体」がVRChat公式
    // VRCPhysBoneの実際の挙動(Ignore Transformsに指定したTransform以下は
    // 物理演算対象から除外される)と一致する。
    internal static List<List<string>> BuildPhysBoneLeafChains(
        string anchorName, IDictionary<string, List<string>> childrenByName, ISet<string> ignoreNames)
    {
        var chainsOut = new List<List<string>>();
        List<string> directChildren;
        if (!childrenByName.TryGetValue(anchorName, out directChildren)) return chainsOut;
        foreach (var c in directChildren)
        {
            if (ignoreNames != null && ignoreNames.Contains(c)) continue;
            CollectPhysBoneLeafChainsPure(c, new List<string>(), chainsOut, childrenByName, ignoreNames);
        }
        return chainsOut;
    }

    // BuildPhysBoneLeafChainsのヘルパー: nameを起点に、子孫のリーフ(ignoreNames
    // で除外されない子を持たないノード)ごとに「起点からリーフまでの名前列」を
    // 1チェーンとしてchainsOutへ積む再帰。currentChainはname自身を含めた状態で
    // 渡される(呼び出し元がanchorの直接の子で最初のnameを積む)。
    internal static void CollectPhysBoneLeafChainsPure(
        string name, List<string> currentChain, List<List<string>> chainsOut,
        IDictionary<string, List<string>> childrenByName, ISet<string> ignoreNames)
    {
        currentChain.Add(name);
        List<string> allChildren;
        var realChildren = new List<string>();
        if (childrenByName.TryGetValue(name, out allChildren))
        {
            foreach (var c in allChildren)
                if (ignoreNames == null || !ignoreNames.Contains(c))
                    realChildren.Add(c);
        }
        if (realChildren.Count == 0)
        {
            chainsOut.Add(currentChain);
            return;
        }
        foreach (var c in realChildren)
        {
            var branch = new List<string>(currentChain);
            CollectPhysBoneLeafChainsPure(c, branch, chainsOut, childrenByName, ignoreNames);
        }
    }
    // D2P_PBCHAIN_PURE_END

    // dev#1104残課題(C:\P\Work\DiveToPalworld\work\lane_1104_texaudit、実測は
    // PROGRESS_dev1104_texaudit.md参照): 実ユーザー報告(V9QTNUMH)で、
    // material_map.jsonの"texture"は非nullなのに実PNGがFBXの隣に無い(=Blender側
    // step01_import_vrm.pyのcopy_tex()が無警告でNoneへ縮退→単色フォールバック→
    // プレビューのガンマ補正で白飛び)という症状が起きた。診断強化(dev#1104
    // PR #1114、Blender側)は既にマージ済みだが、Unity書き出し側の根因は
    // ログ・コードのみからは特定できていない。実機再現ハーネス(reflection経由で
    // 本メソッドを直接叩く合成テクスチャ試験、5パターン)で確定した2件を修正する:
    //   (a) 0x0/不正サイズのテクスチャでRenderTexture.GetTemporaryが
    //       ArgumentExceptionを投げ、どこにも捕捉されずExport()全体(=アバター
    //       輸出全体)を巻き込んで中断していた(実測で再現)。
    //   (b) File.WriteAllBytesが例外を投げなければ即成功扱いで、書き込み直後の
    //       自己検証が一切無かった。SaveTexture自身は実測した範囲(isReadable=false・
    //       DXT5圧縮・RenderTextureソース・8192四方の巨大テクスチャいずれも正常)
    //       では「成功を返しつつファイルが無い」内部経路は再現できなかったが、
    //       原因不明の外部要因(実行環境固有のGPU/ドライバ挙動、AV等)が
    //       将来また同じ症状を起こした場合に備え、書いた直後にFile.Exists+
    //       サイズ>0を確認してから初めて成功を返す構造にする(確認できなければ
    //       単色フォールバックへ落とし、警告ログへ理由を残す——原因の特定は
    //       できなくても、次回以降は「成功したのに結果が変」を「ログに警告が
    //       残っている」へ変える)。
    // どちらのケースも、単一テクスチャの異常でアバター全体の輸出を失敗させず、
    // mainTexture==nullの既存の単色フォールバックと同じ扱いに落として続行する
    // (CLAUDE.md「検証の作法」: 値を寄せて合わせず、失敗経路を構造として塞ぐ)。
    static string SaveTexture(Texture tex, string outDir, Dictionary<Texture, string> cache,
        string materialNameForLog = "")
    {
        string cached;
        if (cache.TryGetValue(tex, out cached)) return cached;

        if (tex.width <= 0 || tex.height <= 0)
        {
            Debug.LogWarning("D2P: texture '" + tex.name + "' on material '" +
                materialNameForLog + "' has an invalid size (" + tex.width + "x" + tex.height +
                ") — falling back to a solid color, this material will not carry its texture");
            return null;
        }

        string file = string.Format("tex_{0:00}.png", cache.Count);
        string outPath = Path.Combine(outDir, file);
        try
        {
            // どんな圧縮形式でもRenderTexture経由で読めるPNGにする
            var rt = RenderTexture.GetTemporary(tex.width, tex.height, 0,
                RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
            Graphics.Blit(tex, rt);
            var prev = RenderTexture.active;
            RenderTexture.active = rt;
            var read = new Texture2D(tex.width, tex.height, TextureFormat.RGBA32, false);
            read.ReadPixels(new Rect(0, 0, tex.width, tex.height), 0, 0);
            read.Apply();
            RenderTexture.active = prev;
            RenderTexture.ReleaseTemporary(rt);
            var pngBytes = read.EncodeToPNG();
            UnityEngine.Object.DestroyImmediate(read);
            if (pngBytes == null || pngBytes.Length == 0)
            {
                Debug.LogWarning("D2P: EncodeToPNG produced no data for texture '" + tex.name +
                    "' on material '" + materialNameForLog +
                    "' — falling back to a solid color, this material will not carry its texture");
                return null;
            }
            File.WriteAllBytes(outPath, pngBytes);
        }
        catch (Exception e)
        {
            Debug.LogWarning("D2P: failed to export texture '" + tex.name + "' on material '" +
                materialNameForLog + "' (" + e.GetType().Name + ": " + e.Message +
                ") — falling back to a solid color, this material will not carry its texture");
            return null;
        }

        // dev#1104残課題(b): 書き込み直後の自己検証。「例外が飛ばなかった」だけを
        // 成功の根拠にしない(理由の項は上のコメント参照)。
        if (!File.Exists(outPath) || new FileInfo(outPath).Length == 0)
        {
            Debug.LogWarning("D2P: texture PNG did not verify immediately after writing " +
                "(missing or empty): " + outPath + " (material '" + materialNameForLog +
                "', texture '" + tex.name +
                "') — falling back to a solid color, this material will not carry its texture");
            return null;
        }

        cache[tex] = file;
        return file;
    }

    static string J(string s)
    {
        return s.Replace("\\", "\\\\").Replace("\"", "\\\"");
    }
}

// dev#250: 必須Humanoidボーンが未割当で、名前からの自動推定も曖昧/該当なし
// だったときに、Unity Editor上のExport Avatarメニュー実行(ユーザーがその場に
// いる対話的な操作)に限って表示する候補選択ダイアログ。バッチ実行では
// 使わない(DiveToPalworldExporter.ApplyBoneNameSuggestionsがApplication.
// isBatchModeで分岐する)。dev#236が禁じた「起動時セットアップの押し付け
// モーダル」とは異なり、ユーザーが選んだExportという操作の延長で出す
// ユーザー起点の対話なので許容される。
internal class BoneChoiceWindow : EditorWindow
{
    string humanLabel;
    DiveToPalworldExporter.BoneSuggestStatus status;
    List<string> candidateNames;
    List<string> candidateDescriptions;
    string result;
    bool done;

    public static string PickBone(string humanLabel,
        DiveToPalworldExporter.BoneSuggestStatus status,
        List<string> candidateNames, List<Transform> allTransforms)
    {
        var window = ScriptableObject.CreateInstance<BoneChoiceWindow>();
        window.titleContent = new GUIContent("DiveToPalworld: ボーン割当の確認");
        window.humanLabel = humanLabel;
        window.status = status;
        window.candidateNames = candidateNames;
        window.candidateDescriptions = new List<string>();
        foreach (var n in candidateNames)
        {
            string path = n;
            foreach (var t in allTransforms)
            {
                if (t != null && t.name == n)
                {
                    path = BuildHierarchyPathForDialog(t);
                    break;
                }
            }
            window.candidateDescriptions.Add(n + "  (" + path + ")");
        }
        window.minSize = new Vector2(520, 220);
        window.result = null;
        window.done = false;
        window.ShowModal();
        return window.done ? window.result : null;
    }

    static string BuildHierarchyPathForDialog(Transform t)
    {
        var sb = new StringBuilder(t.name);
        for (var p = t.parent; p != null; p = p.parent)
            sb.Insert(0, p.name + "/");
        return sb.ToString();
    }

    void OnGUI()
    {
        EditorGUILayout.LabelField(
            "必須Humanoidボーン '" + humanLabel + "' が未割当です。",
            EditorStyles.wordWrappedLabel);
        string hint = status == DiveToPalworldExporter.BoneSuggestStatus.Ambiguous
            ? "名前から複数の候補が見つかりました。正しいものを選択してください:"
            : "名前から一致する候補が見つかりませんでした。近い候補から選ぶか、" +
              "キャンセルしてUnity側(Rigタブ > Configure Avatar)で割り当ててください:";
        EditorGUILayout.LabelField(hint, EditorStyles.wordWrappedLabel);
        EditorGUILayout.Space();
        for (int i = 0; i < candidateDescriptions.Count; i++)
        {
            if (GUILayout.Button(candidateDescriptions[i]))
            {
                result = candidateNames[i];
                done = true;
                Close();
                return;
            }
        }
        EditorGUILayout.Space();
        if (GUILayout.Button("キャンセル(このアバターの輸出を中止する)"))
        {
            done = false;
            Close();
        }
    }
}
