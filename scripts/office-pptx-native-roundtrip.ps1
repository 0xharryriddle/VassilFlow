[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("PowerPoint", "WPS")]
    [string]$Producer,

    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [string]$ReceiptPath,

    [switch]$Overwrite
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-OptionalComProperty {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ComObject,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    try {
        return [string]$ComObject.$Name
    }
    catch {
        return $null
    }
}

function Get-PptxApplicationMetadata {
    param([Parameter(Mandatory = $true)][string]$Path)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $entry = $archive.GetEntry("docProps/app.xml")
        if ($null -eq $entry) {
            throw "Native round-trip output is missing docProps/app.xml"
        }
        $stream = $entry.Open()
        $reader = [System.IO.StreamReader]::new($stream)
        try {
            $document = [System.Xml.XmlDocument]::new()
            $document.PreserveWhitespace = $true
            $document.LoadXml($reader.ReadToEnd())
        }
        finally {
            $reader.Dispose()
            $stream.Dispose()
        }
        $namespaces = [System.Xml.XmlNamespaceManager]::new($document.NameTable)
        $namespaces.AddNamespace("ep", "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties")
        $application = $document.SelectSingleNode("/ep:Properties/ep:Application", $namespaces)
        $appVersion = $document.SelectSingleNode("/ep:Properties/ep:AppVersion", $namespaces)
        return [pscustomobject]@{
            Application = if ($null -eq $application) { $null } else { $application.InnerText }
            AppVersion = if ($null -eq $appVersion) { $null } else { $appVersion.InnerText }
        }
    }
    finally {
        $archive.Dispose()
    }
}

function Get-PowerPointExecutable {
    $candidates = @()
    foreach ($registryPath in @(
        "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE",
        "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE",
        "Registry::HKEY_CURRENT_USER\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE"
    )) {
        try {
            $candidates += Get-ItemPropertyValue -LiteralPath $registryPath -Name "(default)" -ErrorAction Stop
        }
        catch {}
    }
    $command = Get-Command POWERPNT.EXE -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) {
        $candidates += $command.Source
    }
    $candidates += @(
        "C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",
        "C:\Program Files (x86)\Microsoft Office\root\Office16\POWERPNT.EXE",
        "C:\Program Files\Microsoft Office\Office16\POWERPNT.EXE",
        "C:\Program Files (x86)\Microsoft Office\Office16\POWERPNT.EXE"
    )
    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace([string]$candidate)) {
            continue
        }
        $expanded = [Environment]::ExpandEnvironmentVariables(([string]$candidate).Trim('"'))
        if (Test-Path -LiteralPath $expanded -PathType Leaf) {
            return [System.IO.Path]::GetFullPath($expanded)
        }
    }
    return $null
}

function Start-MicrosoftPowerPointAutomation {
    param([Parameter(Mandatory = $true)][string]$ExecutablePath)

    if (@(Get-Process -Name POWERPNT -ErrorAction SilentlyContinue).Count -gt 0) {
        throw "Close Microsoft PowerPoint before running the isolated native round-trip harness"
    }

    $expectedDirectory = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($ExecutablePath)).TrimEnd('\')
    $process = Start-Process -FilePath $ExecutablePath -ArgumentList "/automation" -WindowStyle Hidden -PassThru
    $automation = $null
    try {
        for ($attempt = 0; $attempt -lt 40 -and $null -eq $automation; $attempt++) {
            Start-Sleep -Milliseconds 250
            $candidate = $null
            try {
                $candidate = [Runtime.InteropServices.Marshal]::GetActiveObject("PowerPoint.Application")
                $candidatePath = Get-OptionalComProperty -ComObject $candidate -Name "Path"
                if ([string]::IsNullOrWhiteSpace($candidatePath)) {
                    continue
                }
                $actualDirectory = [System.IO.Path]::GetFullPath($candidatePath).TrimEnd('\')
                if ($actualDirectory -ieq $expectedDirectory -and -not $process.HasExited) {
                    $automation = $candidate
                    $candidate = $null
                }
            }
            catch {}
            finally {
                if ($null -ne $candidate) {
                    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($candidate)
                }
            }
        }
        if ($null -eq $automation) {
            throw "Microsoft PowerPoint automation did not register an owned instance"
        }
        return [pscustomobject]@{
            Application = $automation
            Process = $process
        }
    }
    catch {
        if ($null -ne $automation) {
            try { $automation.Quit() } catch {}
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($automation)
        }
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
        }
        throw
    }
}

$source = (Resolve-Path -LiteralPath $InputPath).Path
$destination = [System.IO.Path]::GetFullPath($OutputPath)
if ([System.IO.Path]::GetExtension($source) -ine ".pptx" -or [System.IO.Path]::GetExtension($destination) -ine ".pptx") {
    throw "Native round-trip input and output must both use .pptx"
}
if ($source -ieq $destination) {
    throw "Native round-trip requires a distinct output path"
}
if (Test-Path -LiteralPath $destination) {
    if (-not $Overwrite) {
        throw "Destination already exists: $destination"
    }
    Remove-Item -LiteralPath $destination -Force
}
$destinationDirectory = Split-Path -Parent $destination
if (-not (Test-Path -LiteralPath $destinationDirectory)) {
    New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
}

$producerId = if ($Producer -eq "PowerPoint") { "microsoft_powerpoint" } else { "wps_presentation" }
$progIds = if ($Producer -eq "PowerPoint") {
    @("PowerPoint.Application")
}
else {
    @("KWPP.Application", "KWPP.Application.12")
}
$progId = $progIds | Where-Object { $null -ne [type]::GetTypeFromProgID($_, $false) } | Select-Object -First 1
if ($null -eq $progId) {
    throw "$Producer COM automation is unavailable. Install the native application and rerun; this harness has no fallback producer."
}

$sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
$application = $null
$presentation = $null
$powerPointProcess = $null
try {
    $application = New-Object -ComObject $progId
    if ($Producer -eq "PowerPoint") {
        $powerPointExecutable = Get-PowerPointExecutable
        $registeredPath = Get-OptionalComProperty -ComObject $application -Name "Path"
        $expectedPath = if ($null -eq $powerPointExecutable) {
            $null
        }
        else {
            [System.IO.Path]::GetDirectoryName($powerPointExecutable)
        }
        if ($null -eq $expectedPath -or $registeredPath -ine $expectedPath) {
            try { $application.Quit() } catch {}
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
            $application = $null
            if ($null -eq $powerPointExecutable) {
                throw "PowerPoint.Application resolves to a non-Microsoft application and POWERPNT.EXE was not found"
            }
            $launched = Start-MicrosoftPowerPointAutomation -ExecutablePath $powerPointExecutable
            $application = $launched.Application
            $powerPointProcess = $launched.Process
        }
    }
    $producerVersion = Get-OptionalComProperty -ComObject $application -Name "Version"
    $producerBuild = Get-OptionalComProperty -ComObject $application -Name "Build"
    $presentation = $application.Presentations.Open($source, -1, 0, 0)
    $presentation.SaveAs($destination, 24)
    $presentation.Close()
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($presentation)
    $presentation = $null
}
finally {
    if ($null -ne $presentation) {
        try { $presentation.Close() } catch {}
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($presentation)
    }
    if ($null -ne $application) {
        try { $application.Quit() } catch {}
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
    }
    if ($null -ne $powerPointProcess) {
        Start-Sleep -Milliseconds 500
        if (-not $powerPointProcess.HasExited) {
            Stop-Process -Id $powerPointProcess.Id -Force
        }
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
    throw "Native producer did not create the requested output"
}
if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sourceHash) {
    throw "Native producer modified the immutable source"
}

$metadata = Get-PptxApplicationMetadata -Path $destination
if ($Producer -eq "PowerPoint" -and $metadata.Application -ne "Microsoft Office PowerPoint") {
    throw "PowerPoint output has unexpected Application metadata: $($metadata.Application)"
}
if ($Producer -eq "WPS" -and $metadata.Application -notmatch "WPS|Kingsoft") {
    throw "WPS output has unexpected Application metadata: $($metadata.Application)"
}

$receipt = [ordered]@{
    schema_version = 1
    producer = $producerId
    prog_id = $progId
    producer_version = $producerVersion
    producer_build = $producerBuild
    package_application = $metadata.Application
    package_app_version = $metadata.AppVersion
    input_file = [System.IO.Path]::GetFileName($source)
    input_sha256 = $sourceHash
    output_file = [System.IO.Path]::GetFileName($destination)
    output_sha256 = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    generated_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
}

if ($ReceiptPath) {
    $receiptDestination = [System.IO.Path]::GetFullPath($ReceiptPath)
    if ((Test-Path -LiteralPath $receiptDestination) -and -not $Overwrite) {
        throw "Receipt already exists: $receiptDestination"
    }
    $receiptDirectory = Split-Path -Parent $receiptDestination
    if (-not (Test-Path -LiteralPath $receiptDirectory)) {
        New-Item -ItemType Directory -Path $receiptDirectory -Force | Out-Null
    }
    $receiptJson = ($receipt | ConvertTo-Json) + [Environment]::NewLine
    $utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($receiptDestination, $receiptJson, $utf8WithoutBom)
}

$receipt | ConvertTo-Json
