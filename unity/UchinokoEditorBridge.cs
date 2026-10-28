// Local file bridge for a running Editor. One fixed operation: export a saved prefab.
// It never saves scenes, executes arbitrary methods, or releases the project's lock.
using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEditor.PackageManager;
using UnityEditor.PackageManager.Requests;
using UnityEngine;

namespace Uchinoko.Reborn.EditorExport
{
    [InitializeOnLoad]
    public static class UchinokoEditorBridge
    {
        // JsonUtility populates these serialized request fields.
#pragma warning disable 0649
        [Serializable] class Request
        {
            public int protocol;
            public string id, prefab, output, fingerprint;
            public long expiresUtc;
            public int clientPid;
        }
#pragma warning restore 0649
        [Serializable] class Ready { public string fingerprint; }
        [Serializable] class Result { public string id, status, message; }
        [Serializable] class Running { public string id; public int editorPid; }
        static readonly string Project = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
        static readonly string State = Path.Combine(Project, "Library/UchinokoRebornBridge");
        static readonly string RequestPath = Path.Combine(State, "request.json");
        static string fingerprint;
        static double nextPoll;
        static AddRequest packageAdd;
        static bool busy;

        static UchinokoEditorBridge()
        {
            // Initialization occurs after source import/domain reload. Do not refresh
            // this fingerprint from an old assembly after scripts on disk change.
            EditorApplication.update += Initialize;
        }

        static void Initialize()
        {
            if (EditorApplication.isCompiling || EditorApplication.isUpdating) return;
            EditorApplication.update -= Initialize;
            try
            {
                Directory.CreateDirectory(State);
                var hashes = new StringBuilder();
                foreach (string name in new[] { "D2PConstraintDiag.cs", "DiveToPalworldExporter.cs", "UchinokoEditorBridge.cs" })
                    hashes.Append(Hash(File.ReadAllBytes(Path.Combine(Project, "Assets/Editor/UchinokoRebornBridge", name))));
                fingerprint = Hash(Encoding.ASCII.GetBytes(hashes.ToString()));
                WriteJson(Path.Combine(State, "ready.json"), new Ready { fingerprint = fingerprint });
                EditorApplication.update -= Poll;
                EditorApplication.update += Poll;
            }
            catch (Exception e) { Debug.LogWarning("[Uchinoko Reborn] Editor bridge initialization: " + e.Message); }
        }

        static string Hash(byte[] data)
        {
            using (var sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(data)).Replace("-", "").ToLowerInvariant();
        }

        static void WriteJson(string path, object value)
        {
            string temporary = path + ".tmp";
            File.WriteAllText(temporary, JsonUtility.ToJson(value), new UTF8Encoding(false));
            if (File.Exists(path)) File.Replace(temporary, path, null);
            else File.Move(temporary, path);
        }

        static void Report(Request request, string status, string message)
        {
            WriteJson(Path.Combine(State, "result.json"), new Result { id = request.id, status = status, message = message });
        }

        static void RemoveMatchingRequest(Request request)
        {
            if (request == null || !File.Exists(RequestPath)) return;
            var pending = JsonUtility.FromJson<Request>(File.ReadAllText(RequestPath));
            if (pending != null && pending.id == request.id) File.Delete(RequestPath);
        }

        static bool IsInside(string path, string directory)
        {
            return path.StartsWith(directory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
        }

        static void Validate(Request request)
        {
            if (request == null || request.protocol != 1 || string.IsNullOrEmpty(request.id)
                || request.id.Length != 32 || request.fingerprint != fingerprint)
                throw new InvalidOperationException("Invalid or outdated export request");
            Guid parsed;
            if (!Guid.TryParseExact(request.id, "N", out parsed)) throw new InvalidOperationException("Invalid request identifier");
            if (request.expiresUtc < DateTimeOffset.UtcNow.ToUnixTimeSeconds()) throw new InvalidOperationException("Export request expired; retry from Uchinoko Reborn");
            using (var client = System.Diagnostics.Process.GetProcessById(request.clientPid))
                if (client.HasExited) throw new InvalidOperationException("Export client has exited");
            if (string.IsNullOrEmpty(request.prefab) || Path.IsPathRooted(request.prefab))
                throw new InvalidOperationException("Prefab must be project-relative");
            string source = Path.GetFullPath(Path.Combine(Project, request.prefab));
            if (!IsInside(source, Path.GetFullPath(Application.dataPath)) || !File.Exists(source)
                || !string.Equals(Path.GetExtension(source), ".prefab", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Request must select a saved prefab in this project's Assets folder");
            if (string.IsNullOrEmpty(request.output) || !Path.IsPathRooted(request.output))
                throw new InvalidOperationException("Output must be an absolute local path");
            string output = Path.GetFullPath(request.output);
            if (output.StartsWith("\\\\") || IsInside(output, Project) || string.Equals(output, Project, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Export output must be outside the Unity project on a local drive");
        }

        static void Poll()
        {
            if (busy || EditorApplication.timeSinceStartup < nextPoll) return;
            nextPoll = EditorApplication.timeSinceStartup + .5;
            if (EditorApplication.isCompiling || EditorApplication.isUpdating || !File.Exists(RequestPath)) return;
            Request request = null;
            bool claimed = false;
            try
            {
                request = JsonUtility.FromJson<Request>(File.ReadAllText(RequestPath));
                Validate(request);
                if (EditorApplication.isPlayingOrWillChangePlaymode || EditorApplication.isPaused)
                {
                    Report(request, "waiting", "Leave Unity Play mode to export the saved prefab.");
                    return;
                }
                // Use Unity's package manager, never rewrite a manifest under an open
                // Editor. Domain reload is expected; the request survives it on disk.
                if (packageAdd != null)
                {
                    if (!packageAdd.IsCompleted) return;
                    var completed = packageAdd;
                    packageAdd = null;
                    if (completed.Status == StatusCode.Failure)
                        throw new InvalidOperationException("FBX Exporter installation failed: " + completed.Error.message);
                }
                if (FindFbxExporter() == null)
                {
                    Report(request, "dependency", "Installing Unity FBX Exporter 4.2.1 for this project (one time).");
                    packageAdd = Client.Add("com.unity.formats.fbx@4.2.1");
                    return;
                }
                // Claim once. A cancelled/dead client cannot enqueue a deferred job.
                WriteJson(Path.Combine(State, "running.json"), new Running {
                    id = request.id, editorPid = System.Diagnostics.Process.GetCurrentProcess().Id });
                claimed = true;
                RemoveMatchingRequest(request);
                busy = true;
                Report(request, "exporting", "Exporting saved prefab in the open Unity Editor...");
                Directory.CreateDirectory(request.output);
                string logPath = Path.Combine(request.output, "unity_export.log");
                using (var log = new StreamWriter(logPath, false, new UTF8Encoding(false)))
                {
                    Application.LogCallback callback = (message, stack, type) =>
                    {
                        log.WriteLine(message);
                        if (!string.IsNullOrEmpty(stack)) log.WriteLine(stack);
                        log.Flush();
                    };
                    Application.logMessageReceived += callback;
                    try
                    {
                        DiveToPalworldExporter.ExportForEditorBridge(request.prefab, request.output);
                        log.WriteLine("D2P_EXPORT_DONE " + request.output);
                    }
                    catch (Exception e) { log.WriteLine(e.ToString()); throw; }
                    finally { Application.logMessageReceived -= callback; }
                }
                Report(request, "done", "Prefab export complete; your Unity project remains open.");
            }
            catch (Exception e)
            {
                if (request != null)
                {
                    try { Report(request, "error", e.ToString()); } catch { }
                }
                // A cancelled client may have been replaced while an export was
                // running. Never consume the replacement client's request.
                try { RemoveMatchingRequest(request); } catch { }
                Debug.LogException(e);
            }
            finally
            {
                if (claimed)
                {
                    string runningPath = Path.Combine(State, "running.json");
                    try
                    {
                        var running = JsonUtility.FromJson<Running>(File.ReadAllText(runningPath));
                        if (running != null && running.id == request.id) File.Delete(runningPath);
                    }
                    catch (IOException) { }
                }
                busy = false;
            }
        }

        static Type FindFbxExporter()
        {
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                var type = assembly.GetType("UnityEditor.Formats.Fbx.Exporter.ModelExporter");
                if (type != null) return type;
            }
            return null;
        }
    }
}
