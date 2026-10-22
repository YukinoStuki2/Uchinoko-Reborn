using System.Text;
using UnityEngine;

// dev#1174: 重複armature診断のログ設計の追補(issue #1174コメント2、
// オーナー問答「何のconstraintを消したかのログは要る?既にある?」への回答)。
//
// 機構仮説(issue #1174コメント1): 「骨格が2つあってconstraintで追従している」
// 型の重複armatureは、VRM/FBX書き出しでconstraintが消える(glTF系は
// constraint非対応)ため、衣装側骨格がレスト姿勢のまま原点付近に置き去りに
// なる。VRM経路はユーザーの書き出し時点で既にconstraintが消えており
// ファイルに情報が存在しないため記録不可能。prefab経路はUnityシーンを
// 直接見られるため、輸出直前(constraint除去前)に「どのボーンにどの
// constraintが付いていたか」をログへ記録できる——本ファイルがそれを行う
// (診断精度向上+「元constraint追従」だったことの断定材料)。
//
// 呼び出し元: unity\DiveToPalworldExporter.cs の StripConstraints()(輸出専用
// 複製からConstraintコンポーネントを除去する箇所)へ、除去の直前に1行だけ
// 挿入する。ロジック本体をこの新規ファイルに置くのは、
// DiveToPalworldExporter.cs が並行レーン(dev#518)でも編集中のため、同一
// ファイルへの大きな差分を避けて衝突を回避する目的(このWPの指示)。
//
// どのツールが原因かは一切言わない(CLAUDE.md 2026-07-29裁定。特定ツールの
// 名指しは製品コード・ログ・エラーメッセージ・公開文面のいずれでも禁止)。
// このファイルは汎用の「Constraintコンポーネントが何に何個ついていたか」を
// 記録するだけで、特定ツール由来かどうかの判定は一切行わない。
public static class D2PConstraintDiag
{
    // rootの子孫(root自身含む)にあるUnityEngine.Animations.IConstraint
    // (PositionConstraint/RotationConstraint/ParentConstraint/
    // ScaleConstraint/LookAtConstraint/AimConstraint)を列挙し、
    // ボーン名・型・ソース(追従先)をログへ残す。副作用なし(削除はしない
    // ——削除は呼び出し側のStripConstraints()が別途行う)。
    public static void LogBoneConstraints(GameObject root)
    {
        int n = 0;
        foreach (var c in root.GetComponentsInChildren<UnityEngine.Animations.IConstraint>(true))
        {
            var comp = c as Component;
            if (comp == null) continue;
            n++;
            Debug.Log("D2P[dup-armature-diag]: constraint on bone '"
                + comp.gameObject.name + "' type=" + comp.GetType().Name
                + " weight=" + c.weight.ToString("F3")
                + " sources=[" + SourcesToString(c) + "]"
                + " (will be removed before export; recorded for duplicate-armature diagnosis, dev#1174)");
        }
        if (n > 0)
            Debug.Log("D2P[dup-armature-diag]: " + n + " constraint(s) found before removal");
    }

    static string SourcesToString(UnityEngine.Animations.IConstraint c)
    {
        var sb = new StringBuilder();
        int count = c.sourceCount;
        for (int i = 0; i < count; i++)
        {
            var src = c.GetSource(i);
            if (i > 0) sb.Append(", ");
            sb.Append(src.sourceTransform != null ? src.sourceTransform.name : "(null)");
            sb.Append("@w=").Append(src.weight.ToString("F2"));
        }
        return sb.ToString();
    }
}
