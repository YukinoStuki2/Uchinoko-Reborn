# prefab指定 → Unityをヘッドレス起動してアバター一式を自動輸出する
# 使い方: pwsh -File export_from_unity.ps1 -Prefab "C:\...\Assets\...\avatar.prefab" [-Out <出力フォルダ>]
#         pwsh -File export_from_unity.ps1 -ResolveUnityOnly   # Unity発見だけ検証(診断用、dev#22)
# 出力: FBXコピー + humanoid.json + 実テクスチャPNG + material_map.json
# 対象: Unity 2022.3.x(VRChat想定)。プロジェクトを開いたままだと起動できない
#       (その場合はUnityのメニュー Tools > DiveToPalworld > Export Avatar で手動輸出)
param(
    [string]$Prefab = "",
    [string]$Out = "",
    [switch]$ResolveUnityOnly
)
$ErrorActionPreference = "Stop"
# 2026-07-26: 以前はこの設定が失敗しても空catchで無言で握りつぶしていた
# (pipeline\cli\convert.ps1で同じ形を解消したのと同じ処置)。失敗しても
# 輸出は続行する(方針どおり、挙動は変えない)が、成否と設定試行後の実値を
# 記録し、失敗時はWrite-Hostで理由を出す。Unity起動を伴うため実行検証は
# 未実施(構文解析のみで確認、報告書に明記)。
$__consoleEncodingOk = $true
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    $__consoleEncodingOk = $false
    Write-Host "[WARN] Failed to set [Console]::OutputEncoding (export continues): $($_.Exception.Message)"
}
$__consoleEncodingActual = try { [Console]::OutputEncoding.WebName } catch { "(failed to read)" }
Write-Host ("Console.OutputEncoding (actual value after set attempt): $__consoleEncodingActual / set succeeded=$__consoleEncodingOk")

# ---------------------------------------------------------------------------
# Unityエディタの解決(dev#22: 「Unity 2022.3インストール済みなのに見つからない」対策)
#
# 探索ロジックの正本は pipeline\py\dep_resolver.py(外部依存の共通resolver。
# dev#23設計確定)。**本ps1は探索を一切実装しない殻**であり、Pythonで
# dep_resolver.py を呼んでマーカー "D2P_RESOLVED: " / "D2P_RESOLVE_FAILED" を
# 読むだけ(dev#21の方針: ps1に新しいロジックを書かない。PS5.1互換地雷のため。
# 当初ここに置いたPowerShell版の鏡実装は、検証でJoin-PathのDriveNotFound即死・
# Get-Contentの既定CP932誤読など地雷3件が実証され、撤去した — work\wp_resolver\VERIFY.md)。
#
# 優先順位・戦略(手動指定 settings_unityeditor.txt / D2P_UNITY_EDITOR →
# UnityHub台帳 → 既知パス、2022.3.xの範囲一致)は全て dep_resolver.py 側を参照。
# 探索した全候補と判定はresolverがtrailとして出力し、そのまま画面(=GUIのログ
# ボックス)へ流れる。
#
# Pythonは通常必ず存在する: GUIは起動直後の EnsureBlenderReadyOnStartup() で
# Blender同梱Pythonを取得済みにしてからでないとprefab投入に到達しない。
# Pythonが見つからない=Blenderセットアップ未完了の縮退状態(変換自体が不可能)
# なので、探索せず静的な案内を出して止める。
# 環境変数 D2P_RESOLVER_NO_PYTHON=1 でその縮退経路を強制できる(試験用)。
# ---------------------------------------------------------------------------
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$UnitySettingsFile = Join-Path $Root "settings_unityeditor.txt"

# このツールが検証済みなのはUnity 2022.3.x系のみ(根拠は下の対応バージョン確認の
# コメント参照)。resolverの範囲一致もこの系列で行う。
$SupportedFamily = "2022.3"

function Find-D2PPython {
    # Blender同梱Python(配布: assets\tools\、開発: tools\)→ システムpython の順。
    # WindowsApps直下のpython.exeはMicrosoft Storeへ誘導するスタブなので除外する。
    foreach ($pat in @("assets\tools\*\*\python\bin\python.exe",
                       "tools\*\*\python\bin\python.exe")) {
        # dev#1485: ここは-LiteralPathにしてはならない。$patが意図的な
        # ワイルドカード(assets\tools\*\*\python\bin\python.exe)であり、
        # 展開されることが機能そのもののため。$Root自体が角括弧を含む場合は
        # この探索だけ不発になりうるが、その場合も後段の手動指定
        # フォールバックが受け止める(CLAUDE.md「自動発見は必ず手動指定
        # フォールバックを持つ」)。
        $hit = Get-ChildItem (Join-Path $Root $pat) -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and ($cmd.Source -notmatch "WindowsApps")) { return $cmd.Source }
    return $null
}

# dev#7: 診断ログへUnityプロジェクトパス・Unityインストール先の生フルパスを無加工で
# 出していた穴の修正(TRIAGE指摘: 本ファイルはマスク処理ゼロ。実ユーザー報告4AL4M4GTで
# 実証)。
#
# dev#480: 以前はここで python.exe(pipeline\py\path_privacy.py factify)を診断表示
# 1回につき毎回外部起動していた。コンソール無し親(GUI経由起動時)から素の `&` で
# コンソールサブシステムの子を起動すると新規コンソールウィンドウが割り当てられ、
# 短命×連射×操作直後という条件が重なって可視化しうる(dev#474 静的調査で発見)。
# C#側の全プロセス起動は CreateNoWindow=true で統一済みなのに、ここだけ非対称だった。
#
# 対処方針(dev#21「ロジックはPython側」との整合を本WPで判断):
# 伏字化ロジックの"正"は引き続き pipeline\py\path_privacy.py 側(GUI本体等、Pythonから
# 直接呼ぶ経路)。ただし本ps1は診断表示のためだけにプロセスを起動すること自体を
# 根絶する必要があるため、pipeline\cli\convert.ps1 に既にある「外部プロセスを一切
# 起動しない純PowerShell実装」の Get-SafeValue / Get-PathFacts / Format-DiagPath を
# ここへ複製する(convert.ps1側は元々この形で、探索・変換ロジックの再実装ではなく
# 表示整形のみに閉じているため dev#21 の対象外という整理は convert.ps1 側で既に
# 確立済み)。
#
# 【対の実装がある】convert.ps1 の Get-SafeValue/Get-PathFacts/Format-DiagPath と
# 本ファイルの同名関数は意図的な複製。ps1ファイル同士のdot-source共有は双方が
# トップレベルで実行される一気通貫スクリプトのため素直には組めず、本WPの範囲では
# 見送った(将来 pipeline\cli\_common.ps1 のような共通モジュール化を検討する余地は
# ある)。**どちらかを変更したら、もう一方も追随させること**(自動乖離検出は無い。
# 2026-08-02時点、tests\convert_diag_path と対になる本ファイル用テストが両方に
# 存在するので、少なくとも既存挙動の回帰は個別に検出できる)。
#
# 挙動差の評価: 旧Python版は `factify --base $Root` で $Root(アプリ配置ルート)配下
# なら相対パス表示していたが、本ps1が扱う $Prefab/$proj はユーザー自身のUnity
# プロジェクト配下であり$Root配下になることは通常無いため、実運用では旧実装も
# 「ファイル名+事実」側に落ちるケースが大半だった。よって convert.ps1 版
# (%USERPROFILE%配下のみトークン化、それ以外はファイル名+Get-PathFacts)への統一で
# 表示の実質的な後退は無いと判断する。
function Get-SafeValue([scriptblock]$Block, [string]$Fallback = "(failed to retrieve)") {
    try { $r = & $Block; if ($null -eq $r -or "$r".Trim() -eq "") { return $Fallback }; return "$r" }
    catch { return "${Fallback}: $($_.Exception.Message)" }
}

function Get-PathFacts([string]$P) {
    if (-not $P) { return "(no path)" }
    $nonAscii = ($P.ToCharArray() | Where-Object { [int]$_ -gt 127 }).Count -gt 0
    $hasSpace = $P.Contains(" ")
    $isUnc = $P.StartsWith("\\")
    $oneDrive = Get-SafeValue { $env:OneDrive } ""
    $underOneDrive = ($oneDrive -and $oneDrive -ne "(failed to retrieve)" -and $P.StartsWith($oneDrive, [System.StringComparison]::OrdinalIgnoreCase))
    return "len=$($P.Length) nonAscii=$nonAscii hasSpace=$hasSpace UNC=$isUnc underOneDrive=$underOneDrive"
}

function Format-DiagPath([string]$P) {
    if (-not $P) { return $P }
    try {
        $up = [Environment]::GetFolderPath("UserProfile")
        if ($up -and $P.StartsWith($up, [System.StringComparison]::OrdinalIgnoreCase)) {
            return "%USERPROFILE%" + $P.Substring($up.Length)
        }
    } catch {}
    $name = $null
    try { $name = Split-Path $P -Leaf } catch {}
    if (-not $name) { $name = "(name unavailable)" }
    return "$name (path masked; " + (Get-PathFacts $P) + ")"
}

# dev#480: dep_resolver.py の呼び出しは(Format-DiagPathと違い)ロジック本体が
# Python側にあるため引き続き外部プロセス起動が必要(dev#21方針どおり)。ただし
# 素の `&` はコンソールサブシステムの子に新規コンソールを割り当てうるため、
# C#側(全9箇所CreateNoWindow=true)と同じ土俵に揃えるべく
# System.Diagnostics.ProcessStartInfo で CreateNoWindow=$true / UseShellExecute=$false
# を明示して包む。旧実装が2>&1でマージしていたstdout/stderrは、ここでは個別に
# 読み取ってから連結する(順序の完全な一致は保証されないが、呼び出し側は
# "D2P_RESOLVED: " / "D2P_RESOLVE_FAILED" マーカーの有無だけを見ており、
# 行の到着順には依存していない)。
# dev#480実測: [System.Diagnostics.ProcessStartInfo]::ArgumentList は Windows
# PowerShell 5.1(.NET Framework)では $null のままで、.Add()呼び出しが
# "You cannot call a method on a null-valued expression" で即死する
# (pwsh/.NET Coreでは正常に動くため見落としやすい罠。app_py\pipeline_runner.py の
# find_pwsh() は pwsh.exe が無い環境では powershell.exe へフォールバックする設計
# なので、この経路は実際に踏まれうる。PS5.1互換地雷はdev#21が警告する典型パターン)。
# よってArgumentListは使わず、昔ながらの単一Arguments文字列(Win32コマンドライン
# 引用規則で自前クォート)を組み立てる。
function ConvertTo-D2PQuotedArg([string]$Arg) {
    if ($null -eq $Arg) { $Arg = "" }
    if ($Arg -eq "" -or $Arg -match '[\s"]') {
        return '"' + ($Arg -replace '"', '\"') + '"'
    }
    return $Arg
}

function Invoke-D2PPythonNoWindow([string]$PythonExe, [string[]]$ArgumentList, [hashtable]$EnvOverrides) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $PythonExe
    $psi.Arguments = (($ArgumentList | ForEach-Object { ConvertTo-D2PQuotedArg $_ }) -join " ")
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    if ($EnvOverrides) {
        foreach ($k in $EnvOverrides.Keys) { $psi.EnvironmentVariables[$k] = $EnvOverrides[$k] }
    }
    $proc = [System.Diagnostics.Process]::Start($psi)
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    $proc.WaitForExit()
    $lines = @()
    if ($stdout) { $lines += @($stdout -split "`r?`n") }
    if ($stderr) { $lines += @($stderr -split "`r?`n") }
    $lines = $lines | Where-Object { $_ -ne "" }
    return [PSCustomObject]@{ Lines = $lines; ExitCode = $proc.ExitCode }
}

function Resolve-D2PUnityEditor([string]$ProjectVersion, [string]$Family) {
    # 返り値: Unity.exeのフルパス。見つからなければ $null(trail+案内は出力済み)。
    if ($env:D2P_RESOLVER_NO_PYTHON -ne "1") {
        $py = Find-D2PPython
        if ($py) {
            $resolverPy = Join-Path $Root "pipeline\py\dep_resolver.py"
            if (Test-Path -LiteralPath $resolverPy -PathType Leaf) {
                Write-Host "Dependency resolution: using pipeline\py\dep_resolver.py (python: $py)"
                $argsList = @($resolverPy, "unity_editor", "--approot", $Root)
                if ($ProjectVersion) { $argsList += @("--project-version", $ProjectVersion) }
                $envOverrides = @{ PYTHONIOENCODING = "utf-8"; PYTHONUTF8 = "1" }
                $result = Invoke-D2PPythonNoWindow -PythonExe $py -ArgumentList $argsList -EnvOverrides $envOverrides
                $out = $result.Lines
                $code = $result.ExitCode
                foreach ($line in $out) { Write-Host $line }
                if ($code -eq 0) {
                    $hit = $out | Where-Object { $_ -like "D2P_RESOLVED: *" } | Select-Object -Last 1
                    if ($hit) { return $hit.Substring("D2P_RESOLVED: ".Length).Trim() }
                }
                if ($out -match "D2P_RESOLVE_FAILED") {
                    return $null  # trail+手動指定案内はresolverが出力済み
                }
                Write-Host "dep_resolver.py did not produce a result (exit=$code)."
            }
        }
    }
    # ここに来る=Pythonが1つも無い(またはresolverが起動すらできない)。
    # これはBlenderセットアップ未完了の縮退状態で、この先の変換も一切できないため、
    # 探索のPowerShell再実装はせず(dev#21)、静的な案内だけ出して止める。
    Write-Host ""
    Write-Host "[dep_resolver] ERROR: could not run the Python resolver (pipeline\py\dep_resolver.py)."
    Write-Host "[dep_resolver] No usable Python was found (searched: $Root\assets\tools, $Root\tools, system PATH), or it failed to start."
    Write-Host "Cannot search for Unity yet because the first-time Blender setup has not finished."
    Write-Host "Please launch the Uchinoko for Palworld app first to complete the first-time Blender"
    Write-Host "setup (automatic download), then try again (both this search and conversion will work"
    Write-Host "once setup is done)."
    Write-Host "If that still does not resolve it, write the full path to your Unity.exe as a single"
    Write-Host "line in the following file to have it used as the manual override (highest priority):"
    Write-Host "  $UnitySettingsFile"
    Write-Host "Example: C:\Program Files\Unity\Hub\Editor\2022.3.22f1\Editor\Unity.exe"
    return $null
}

if ($ResolveUnityOnly) {
    # 診断モード(dev#22): prefab不要でUnity発見だけを検証する(サポート・試験用)。
    $found = Resolve-D2PUnityEditor -ProjectVersion "" -Family $SupportedFamily
    if ($found) {
        Write-Host "Unity: $(Format-DiagPath $found)"
        exit 0
    }
    Write-Error "Unity editor was not found (check the search results and guidance above) [D2P_UNITY_NOT_FOUND]"
    exit 1
}
if (-not $Prefab) {
    Write-Error "Please specify a prefab file (usage: -Prefab `"C:\...\Assets\...\avatar.prefab`")"
    exit 1
}

# 2026-07-26: .Path はUNCパス(\\server\share\...)に対して
# "Microsoft.PowerShell.Core\FileSystem::\\server\share\..." というプロバイダ修飾形を返し、
# 後段のJoin-Path等で壊れたパスになる(大崎商会PCでの`ReadAllBytes`失敗の実因)。
# .ProviderPath はプロバイダ接頭辞なしの素のファイルシステムパスを返すのでこちらを使う。
#
# dev#1485: 実報告35TX8ERYで、実在するprefabファイルを渡したのに
# 「Please specify a prefab file (got: ; ext=)」($Prefabが空)として棄却される
# 不具合の根因がここにあった。Resolve-Path(-LiteralPath無し)は`-Path`を
# ワイルドカード展開する。`[` `]` `*` `?` はいずれもPowerShellのワイルドカード
# 文字だが、VRoid/BoothアセットやUnity資産のファイル/フォルダ名では
# "[PC]" "[base]" のような角括弧タグ付けがごく普通に使われる(実際に上記
# ユーザーのアバター名がその実例)。角括弧を含む実在パスをワイルドカードとして
# 解釈すると一致0件になり、Resolve-Pathは$ErrorActionPreference="Stop"下でも
# 例外を投げず**黙って空文字列を返す**(実機PowerShell 7.6.4で実測確認)。
# これが直後の.EndsWith(".prefab")チェックに落ち、実在ファイルが「未指定」
# として報告される。-LiteralPathで角括弧等を文字どおり扱うことで解消する
# (角括弧を含まない通常パスでの挙動は-LiteralPath有無で完全に同一、実測確認済み)。
$Prefab = (Resolve-Path -LiteralPath $Prefab).ProviderPath
if (-not $Prefab.ToLower().EndsWith(".prefab")) {
    # dev#1105: 実報告35TX8ERYで、この失敗時に実際に渡された $Prefab の値が
    # 一切ログに残らず(固定文言のみ)、ユーザー操作ミスか実装バグ(パス解決
    # 過程での文字列変質)かを診断ログから判別できなかった。実値を出す際は
    # 既存のパス伏字化(Format-DiagPath、上のGet-PathFacts節参照)を経由し、
    # 生パスがサニタイズを迂回してそのまま診断バンドルへ乗らないようにする。
    $extActual = try { [System.IO.Path]::GetExtension($Prefab) } catch { "(failed to retrieve)" }
    Write-Error "Please specify a prefab file (got: $(Format-DiagPath $Prefab); ext=$extActual)"
    exit 1
}

# 1) prefabパスからUnityプロジェクトルートを逆算(Assets/ の親)
$dir = Split-Path $Prefab -Parent
$proj = $null
while ($dir) {
    if ((Split-Path $dir -Leaf) -eq "Assets") { $proj = Split-Path $dir -Parent; break }
    $parent = Split-Path $dir -Parent
    if ($parent -eq $dir) { break }
    $dir = $parent
}
if (-not $proj -or -not (Test-Path -LiteralPath (Join-Path $proj "ProjectSettings\ProjectVersion.txt"))) {
    Write-Error "Could not identify the Unity project (is the prefab under Assets?)"; exit 1
}
$assetRel = $Prefab.Substring($proj.Length + 1).Replace("\", "/")
# dev#7: $proj(Unityプロジェクトルート)はユーザーが既に知っている場所への案内では
# なく純粋な診断表示のため伏字化する。$assetRel はプロジェクト相対パスで個人フォルダ名を
# 含まないためそのまま出す(既存どおり)。
Write-Host "Project: $(Format-DiagPath $proj)"
Write-Host "Asset: $assetRel"

# 2) プロジェクトのUnityバージョンが対応系列(2022.3.x)かを確認してから、エディタを探す
$verLine = (Get-Content -LiteralPath (Join-Path $proj "ProjectSettings\ProjectVersion.txt") | Select-String "m_EditorVersion:").Line
$projVer = ($verLine -split "\s+")[1]
$family = ($projVer -split "\.")[0..1] -join "."

# 2026-07-26: 対応外バージョンでも今までは検出さえできればそのまま先へ進み、
# 後段の無関係な場所(manifest.json操作やUnity起動後)で意味不明なエラーになっていた
# (大崎商会PCでUnity 2019.4.31f1のプロジェクトを渡した実例)。
# このツールが検証済みなのはUnity 2022.3.x系のみ:
#   - このスクリプト冒頭のコメント「対象: Unity 2022.3.x(VRChat想定)」
#   - manual\manual.md「自分のアバターのUnityProjectを開きます(Unity 2022.3.22f1で動作します)」
#   - tests\coverage\README.md「検体4体(いずれも Unity 2022.3.22f1、MA + NDMF 導入済み)」
# のいずれも2022.3.22f1を前提にしている。古い/新しい問わずそれ以外は動作未検証であり、
# 「警告だけ出して通す」ことは今回のような分かりにくい失敗を将来また生むため、
# ここで理由と対処法を示して確実に止める。($SupportedFamilyの定義は冒頭のresolver節)
if ($family -ne $SupportedFamily) {
    $msg = @"
This project's Unity version is not supported.

Supported Unity for this tool: $SupportedFamily family (e.g. 2022.3.22f1)
Detected project Unity: $projVer
Project: $(Format-DiagPath $proj)

What to do:
  1. Reopen your avatar project in a Unity $SupportedFamily family version for VRChat
     (use VRChat Creator Companion (VCC) to change the project's Unity version,
      or create a new $SupportedFamily project and migrate your avatar assets into it)
  2. Specify a prefab in the reopened project and run this command again
"@
    Write-Error $msg
    exit 1
}

# dev#22: 旧実装(C:\Program Files\Unity\Hub\Editor 決め打ち+ディレクトリ名走査のみ)は
# Hubのインストール先変更・別ドライブ・Hub非経由に不可視だった。共通resolver
# (冒頭のresolver節。正本 pipeline\py\dep_resolver.py)で解決する。
$editor = Resolve-D2PUnityEditor -ProjectVersion $projVer -Family $SupportedFamily
if (-not $editor -or -not (Test-Path -LiteralPath $editor)) {
    Write-Error ("Could not find a matching Unity ($projVer / $SupportedFamily family). `n" +
        "Check the search results (trail) above and the manual-override guidance. [D2P_UNITY_NOT_FOUND]")
    exit 1
}
Write-Host "Unity: $(Format-DiagPath $editor) (project=$projVer)"

# 3) プロジェクトが開かれていないか(二重起動はUnityが禁止)
$lock = Join-Path $proj "Temp\UnityLockfile"
if (Test-Path -LiteralPath $lock) {
    try {
        $fs = [IO.File]::Open($lock, "Open", "ReadWrite", "None"); $fs.Close()
    } catch {
        Write-Error ("This project is currently open in Unity. Close Unity and run again, `n" +
            "or use the Unity menu Tools > DiveToPalworld > Export Avatar to export manually")
        exit 1
    }
}

# 3.5) 統合FBX書き出しに必須のFBX Exporterが無ければmanifestへ追記(次回起動時にDL)
#      manifest.json / packages-lock.json は実行前に退避し、finally で必ずバイト単位で復元する
$manifestPath = Join-Path $proj "Packages\manifest.json"
$lockPath = Join-Path $proj "Packages\packages-lock.json"
$manifestBackupBytes = [IO.File]::ReadAllBytes($manifestPath)
$lockBackupBytes = $null
if (Test-Path -LiteralPath $lockPath) { $lockBackupBytes = [IO.File]::ReadAllBytes($lockPath) }
$manifestModified = $false

# manifest.jsonはUTF-8(Unity/VCCが書く)。PS5.1の既定(ANSI/cp932)で誤読したまま
# 下でSet-Content -Encoding utf8で書き戻すと、非ASCII(ローカルパッケージのfile:パス等)を
# 含むmanifestを破壊する。読取は必ずUTF-8明示(起票案1と同族の入口正規化)
$mj = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8
if ($mj -notmatch '"com\.unity\.formats\.fbx"') {
    # JSONラウンドトリップ(ConvertFrom-Json/ConvertTo-Json)はファイル全体の整形を壊すため、
    # "dependencies": { の直後に1行差し込むだけの最小限のテキスト編集にする
    $insertion = "`"com.unity.formats.fbx`": `"4.2.1`","
    $newMj = [System.Text.RegularExpressions.Regex]::Replace(
        $mj,
        '("dependencies"\s*:\s*\{)',
        { param($m) $m.Groups[1].Value + "`n    " + $insertion },
        1
    )
    if ($newMj -eq $mj) {
        Write-Error "Could not find the `"dependencies`" section in manifest.json, so the FBX Exporter could not be added"
        exit 1
    }
    Set-Content -LiteralPath $manifestPath -Value $newMj -Encoding utf8 -NoNewline
    $manifestModified = $true
    Write-Host "Added FBX Exporter (com.unity.formats.fbx 4.2.1) to manifest.json (first run may take time to download)"
}

# 4) エクスポータを注入(冪等)して、ヘッドレスで実行
#    専用サブフォルダに置くことで、実行後にフォルダごと確実に消せる(ユーザーの同名ファイル上書き事故も防ぐ)
# ($Rootは冒頭のresolver節で定義済み)
$editorDir = Join-Path $proj "Assets\Editor"
$editorDirPreexisting = Test-Path -LiteralPath $editorDir
$exporterDir = Join-Path $editorDir "D2P_TempExporter"
$exporterCs = Join-Path $exporterDir "DiveToPalworldExporter.cs"
# dev#1174: StripConstraints()が呼ぶD2PConstraintDiag.LogBoneConstraints()は
# 別ファイル(unity\D2PConstraintDiag.cs、並行レーンdev#518との衝突回避のため
# 分離)にある。DiveToPalworldExporter.cs単体だけを注入すると型が見つからず
# コンパイルエラーになるため、こちらも同じ一時フォルダへ注入する
$constraintDiagCs = Join-Path $exporterDir "D2PConstraintDiag.cs"

try {
    # dev#1485: New-Itemには-LiteralPathが存在しない(PS7.6.4で確認)。ただし
    # -Pathは「作成」用途ではワイルドカード展開しないため、$proj/$Outが角括弧を
    # 含んでいても正常に作成できる(実測確認済み)。ここは素の-Pathのままでよい。
    # 一方Copy-Itemの**ソース側**は展開されるので-LiteralPathが要る($Rootが
    # 角括弧を含むフォルダに配置された場合に効く)。
    New-Item -ItemType Directory -Force $exporterDir | Out-Null
    Copy-Item -LiteralPath (Join-Path $Root "unity\DiveToPalworldExporter.cs") -Destination $exporterCs -Force
    Copy-Item -LiteralPath (Join-Path $Root "unity\D2PConstraintDiag.cs") -Destination $constraintDiagCs -Force
    if (-not $Out) {
        $name = [IO.Path]::GetFileNameWithoutExtension($Prefab)
        $Out = Join-Path $Root "work\${name}_export"
    }
    New-Item -ItemType Directory -Force $Out | Out-Null
    $log = Join-Path $Out "unity_export.log"
    Write-Host "Launching Unity in headless mode (first run may take a few minutes for import)..."
    # dev#480: 検討したが -nographics は追加しない。理由: unity\DiveToPalworldExporter.cs が
    # Camera.Render()/RenderTexture/ReadPixels をエクスポート本流で使っている
    # (サムネイル生成: Camera.Render→RenderTexture.active→ReadPixels、および
    # material_map.json用テクスチャPNG抽出: RenderTexture.GetTemporary→ReadPixels、
    # 2026-08-02時点 unity\DiveToPalworldExporter.cs 内 "cam.Render()"
    # "RenderTexture.GetTemporary" 呼び出し箇所を確認)。Unityの-nographicsは
    # グラフィックデバイスを初期化しないため、これらのレンダリング依存処理が
    # 壊れる具体的なリスクがある。prefab経路(輸出→変換の入口)を壊すコストは
    # コンソール表示問題より遥かに高いため、確認できないまま入れることはしない
    # (WP仕様の指示どおり、疑いが残る場合は入れずに報告)。
    & $editor -batchmode -projectPath $proj -executeMethod DiveToPalworldExporter.ExportBatch `
        -vrm2palPrefab $assetRel -vrm2palOut $Out -quit -logFile $log | Out-Null
    $done = Select-String -LiteralPath $log -Pattern "D2P_EXPORT_DONE" -Quiet
    if (-not $done) {
        # dev#235: 旧実装は先に Write-Error を呼んでいたため、冒頭の
        # $ErrorActionPreference = "Stop" によりWrite-Errorがその場でスクリプトを
        # 終了させ、直後の抜粋処理(旧: 次行のSelect-String)が実行されない
        # 死にコードになっていた(pwsh実験で実測確認: Write-Error後の行は
        # 到達不能。GUIが実際に見ていた要点はC#側 ExtractUnityExportLogHighlights
        # がunity_export.logを独立に再走査した結果だった)。
        # さらに旧パターンはマッチ行そのものだけを最大5件抜き出す実装で、
        # 例外メッセージの直後に続くUnityのスタックトレース行
        # ("... (at Assets/...:NN)" 等、"Exception"という文字列を含まない)を
        # 一切拾えていなかった(dev#150: convert.ps1側の同型欠陥と同一パターン)。
        # 抜粋は必ずWrite-Errorより前に、Write-Host(標準出力)で確実に出す。
        # dev#262: 「輸出」表記は「エクスポート」に統一する(2026-07-30)。
        # dev#696: 後続文脈を15行から40行へ拡大。ExportUnifiedFbxはUnity公式FBX
        # Exporterへ System.Reflection.MethodInfo.Invoke 経由で入るため、実際の
        # 例外発生箇所までのスタックトレースは
        # 「発生箇所 → FBX Exporter内部の呼び出し階層 → MethodBase.Invoke/
        # RuntimeMethodHandle.InvokeMethod → DiveToPalworldExporter側の各メソッド →
        # Unityの-executeMethod起動フレーム」と重なり15行では最内周に届く前に
        # 打ち切られうる。この分岐はUnity輸出失敗時(D2P_EXPORT_DONEマーカーが
        # 無い場合)にのみ実行されるため、正常終了時のログ肥大には影響しない。
        # dev#921: 従来は Select-Object -First 5 でファイル先頭から数えて最初の
        # 5マッチだけを拾っていた。実ログ(6716行)では2169行目付近のNDMFスタック
        # フレーム行("...Log:Write (...,System.Exception) (at Log.cs:NNN)")が
        # "Exception"に当たって5枠を食い潰し、末尾(6650行付近)の本物の例外
        # (Unityバッチ失敗は必ず末尾に "executeMethod ... threw exception." を
        # 出す)に到達しなかった。ファイル末尾に近いマッチほど診断価値が高いため
        # -Last に変える(末尾優先。Select-Object -Lastは入力の末尾N件を元の順序
        # 通りに返すため、抜粋の行内出現順は変わらない)。
        # dev#1262: 実報告4YYV28PZでは、UPMパッケージ版UniVRM(com.vrmc.univrm)と
        # 手動導入版(Assets/VRM/...)の共存によるGUIDインポータ競合
        # ("... conflicts with: ... the asset is in an immutable folder ...")が
        # 大量発生していたが、その行は"Exception"にも"error CS"にも一致せず、
        # 抜粋(=ログ欄・診断ログに載る唯一の情報)へ一切拾われていなかった。
        # "conflicts with"/"immutable folder"をパターンへ追加し、この種の
        # パッケージ競合もログのみで診断できるようにする(GUI側の検出は
        # pipeline_runner.detect_univrm_duplicate_install が担当)。
        Write-Host "Export failed - see log: $log"
        Write-Host "--- Excerpt around the failure (full text is in the log file above) ---"
        $excerpt = Select-String -LiteralPath $log -Pattern "Exception|error CS|conflicts with|immutable folder" -Context 0,40 |
            Select-Object -Last 5
        if ($excerpt) {
            foreach ($m in $excerpt) { Write-Host $m.ToString() }
        } else {
            Write-Host "(No lines containing Exception / error CS / conflicts with / immutable folder were found. Check the full log file.)"
        }
        Write-Host "--- End of excerpt ---"
        Write-Error "Export failed (see the excerpt above and the log file for details)"
        exit 1
    }
    Write-Host ""
    Write-Host "Export complete: $Out"
    Get-ChildItem -LiteralPath $Out | Select-Object Name, Length | Format-Table -AutoSize
    Write-Host "Drag and drop the FBX inside this folder into Uchinoko for Palworld"
}
finally {
    # プロジェクトへの痕跡を必ず消す(Unityが失敗・タイムアウト・例外いずれでもここを通る)
    #
    # dev#1485: これらは元々-ErrorAction SilentlyContinueで例外を握りつぶしていた
    # ため、$proj(ひいてはこの下の各パス)が角括弧を含む場合、ワイルドカード
    # 不一致で自分たちが注入した一時ファイルの削除に**黙って失敗し**、ユーザーの
    # Unityプロジェクト(Assets\Editor\D2P_TempExporter配下)にファイルが残留する
    # 副作用があった。-LiteralPathで実際に消えることを保証する。
    Remove-Item -LiteralPath (Join-Path $exporterDir "DiveToPalworldExporter.cs.meta") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $exporterCs -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $exporterDir "D2PConstraintDiag.cs.meta") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $constraintDiagCs -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $exporterDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath ($exporterDir + ".meta") -Force -ErrorAction SilentlyContinue
    if (-not $editorDirPreexisting -and (Test-Path -LiteralPath $editorDir)) {
        $remaining = Get-ChildItem -LiteralPath $editorDir -Force -ErrorAction SilentlyContinue
        if (-not $remaining) {
            Remove-Item -LiteralPath $editorDir -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath ($editorDir + ".meta") -Force -ErrorAction SilentlyContinue
        }
    }

    # manifest.json / packages-lock.json をバイト単位で復元(片方だけ戻すと不整合になるため両方)
    if ($manifestModified) {
        [IO.File]::WriteAllBytes($manifestPath, $manifestBackupBytes)
        if ($null -ne $lockBackupBytes) {
            [IO.File]::WriteAllBytes($lockPath, $lockBackupBytes)
        } elseif (Test-Path -LiteralPath $lockPath) {
            Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
        }
    }
}
