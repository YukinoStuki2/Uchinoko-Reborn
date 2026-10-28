// Integration fixture only: installed into an isolated test project, never into
// an avatar project. SDK-shaped data exercises reflection without redistributing
// VRChat assemblies. Ratio formulas are verified against SDK 3.10.5 metadata.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEngine;

namespace VRC.SDK3.Dynamics.PhysBone.Components
{
    public class VRCPhysBone : MonoBehaviour
    {
        public enum Version { Version_1_0, Version_1_1 }
        public enum IntegrationType { Simplified, Advanced }
        public enum MultiChildType { Ignore, First, Average }
        public Transform rootTransform;
        public Version version = Version.Version_1_1;
        public IntegrationType integrationType = IntegrationType.Advanced;
        public MultiChildType multiChildType = MultiChildType.Average;
        public Vector3 endpointPosition = new Vector3(.02f, -.04f, .01f);
        public List<Transform> ignoreTransforms = new List<Transform>();
        public bool ignoreOtherPhysBones = true;
        public float pull = .3f, spring = .8f, stiffness = .2f;
        public float gravity = .12f, gravityFalloff = .4f, immobile = .25f;
        public float maxAngleX = 45f, maxAngleZ = 25f, radius = .01f;
        public float stretchMotion = .7f, maxStretch = .2f, maxSquish = .3f;
        public Vector3 limitRotation = new Vector3(4, 5, 6);
        public bool isAnimated = true, resetWhenDisabled = true;
        public AnimationCurve pullCurve = new AnimationCurve();
        public AnimationCurve springCurve, maxAngleXCurve;
        // Other curve fields deliberately absent, exercising SDK-version gaps.
        [NonSerialized] public int maxBoneChainIndex = 777;
        public float CalcBoneRatio(int depth)
        {
            int divisor = maxBoneChainIndex + (endpointPosition != Vector3.zero ? 1 : 0) - 1;
            return divisor <= 0 ? 0 : Mathf.Clamp01((float)depth / divisor);
        }
        public float CalcTransformRatio(int depth)
        {
            return Mathf.Clamp01((float)depth / (maxBoneChainIndex + (endpointPosition != Vector3.zero ? 1 : 0)));
        }
    }
}

public static class UchinokoPhysBoneExportFixture
{
    [Serializable] sealed class Expected
    {
        public bool indexRestored;
        public bool destroyedRootIsUnityNull;
        public bool destroyedRootHasManagedReference;
        public bool destroyedRootFieldPreserved;
        public float weightedAtPointTwo;
        public Vector3 endpointWorld;
    }

    public static void Run()
    {
        var root = new GameObject("PhysBoneFixture");
        try
        {
            root.transform.position = new Vector3(2, 3, 4);
            root.transform.rotation = Quaternion.Euler(20, 35, 10);
            root.transform.localScale = Vector3.one * 2;
            var anchor = Child(root.transform, "Anchor", Vector3.up);
            var b1 = Child(anchor, "Segment1", Vector3.up * .01f);
            var b2 = Child(b1, "Segment2", Vector3.up * .3f);
            var b3 = Child(b2, "Segment3", Vector3.up * .1f);
            var b4 = Child(b3, "Segment4", Vector3.up * .2f);
            var ignored = Child(b1, "Ignored", Vector3.right);
            Child(ignored, "IgnoredTip", Vector3.right);
            var nested = Child(b1, "OtherRoot", Vector3.left);
            Child(nested, "OtherTip", Vector3.left);
            var otherPb = nested.gameObject.AddComponent<VRC.SDK3.Dynamics.PhysBone.Components.VRCPhysBone>();
            // NDMF/armature cleanup can destroy a referenced root while leaving
            // its PhysBone component alive. This is a real Unity fake-null
            // Transform: CLR ?? must not be used to select its fallback root.
            var removedRoot = Child(root.transform, "RemovedByBake", Vector3.zero);
            otherPb.rootTransform = removedRoot;
            UnityEngine.Object.DestroyImmediate(removedRoot.gameObject);
            if (removedRoot != null || ReferenceEquals(removedRoot, null))
                throw new InvalidOperationException("Fixture did not create Unity fake-null reference");
            Debug.Log("UCHINOKO_PHYSBONE_DESTROYED_OTHER_ROOT_READY");

            var pb = anchor.gameObject.AddComponent<VRC.SDK3.Dynamics.PhysBone.Components.VRCPhysBone>();
            pb.ignoreTransforms.Add(ignored);
            var first = new Keyframe(0, .2f, 0, 2, .1f, .7f) { weightedMode = WeightedMode.Both };
            var peak = new Keyframe(.23f, .8f, 0, 0, .3f, .3f) { weightedMode = WeightedMode.Both };
            var last = new Keyframe(1, 1, .3f, 0, .2f, .4f) { weightedMode = WeightedMode.Both };
            pb.springCurve = new AnimationCurve(first, peak, last) { preWrapMode = WrapMode.ClampForever, postWrapMode = WrapMode.Loop };
            pb.maxAngleXCurve = new AnimationCurve(new Keyframe(0, 0, 0, float.PositiveInfinity), new Keyframe(1, 1, float.PositiveInfinity, 0));
            string output = Path.Combine(Path.GetFullPath(Path.Combine(Application.dataPath, "..")), "probe-output");
            Directory.CreateDirectory(output);
            var exporter = typeof(Uchinoko.Reborn.EditorExport.DiveToPalworldExporter);
            exporter.GetMethod("ExtractPhysBoneChains", BindingFlags.Static | BindingFlags.NonPublic)
                .Invoke(null, new object[] { root, output });
            var expected = new Expected {
                indexRestored = pb.maxBoneChainIndex == 777,
                destroyedRootIsUnityNull = removedRoot == null,
                destroyedRootHasManagedReference = !ReferenceEquals(removedRoot, null),
                destroyedRootFieldPreserved = ReferenceEquals(otherPb.rootTransform, removedRoot),
                weightedAtPointTwo = pb.springCurve.Evaluate(.2f),
                endpointWorld = b4.TransformPoint(pb.endpointPosition)
            };
            File.WriteAllText(Path.Combine(output, "expected.json"), JsonUtility.ToJson(expected, true));
            Debug.Log("UCHINOKO_PHYSBONE_EXPORT_PROBE_OK");
        }
        finally { UnityEngine.Object.DestroyImmediate(root); }
    }

    static Transform Child(Transform parent, string name, Vector3 position)
    {
        var child = new GameObject(name).transform;
        child.SetParent(parent, false);
        child.localPosition = position;
        return child;
    }
}
