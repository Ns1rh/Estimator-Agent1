$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

$workspace = 'C:\Users\namid\Documents\Codex\2026-06-22\is'
$python = 'C:\Users\namid\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$agent = Join-Path $workspace 'work\estimating_agent_cli.py'
$defaultScanRoot = '\\Naeserver\naesf\Bids\Bids 2025'
$defaultScanOut = Join-Path $workspace 'outputs\database-prep\bids-2025-scan'
$trainingOut = Join-Path $workspace 'outputs\training-set\bids-2025-good-fixtures'
$coworkerOutRoot = Join-Path $workspace 'outputs\coworker-estimates'
$node = 'C:\Users\namid\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$liveCountBrowserControl = Join-Path $workspace 'work\livecount_browser_control.mjs'
$appControlBridge = Join-Path $workspace 'work\app_control_bridge.ps1'
$liveCountControlOut = Join-Path $workspace 'outputs\livecount-control'

function Pause-Agent {
  Write-Host ""
  Read-Host "Press Enter to continue"
}

function Open-IfExists($path, [switch]$Notepad) {
  if (Test-Path -LiteralPath $path) {
    if ($Notepad) {
      Start-Process notepad.exe -ArgumentList $path
    } else {
      Start-Process $path
    }
  } else {
    Write-Host "Not found: $path" -ForegroundColor Yellow
  }
}

function Show-Info($title, $message) {
  [void][System.Windows.Forms.MessageBox]::Show($message, $title, 'OK', 'Information')
}

function Show-ErrorBox($message) {
  [void][System.Windows.Forms.MessageBox]::Show($message, 'Estimator Agent Error', 'OK', 'Error')
}

function Get-SafeName($name, $fallback) {
  $safeName = ($name -replace '[^A-Za-z0-9._-]+', '_').Trim('_')
  if ([string]::IsNullOrWhiteSpace($safeName)) { return $fallback }
  return $safeName
}

function Normalize-InputPath($path) {
  return ($path.Trim() -replace '^"|"$', '')
}

function Pick-Folder($description) {
  $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
  $dialog.Description = $description
  $dialog.ShowNewFolderButton = $false
  if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    return $dialog.SelectedPath
  }
  return ''
}

function Pick-PdfOrFile($title) {
  $dialog = New-Object System.Windows.Forms.OpenFileDialog
  $dialog.Title = $title
  $dialog.Filter = 'PDF files (*.pdf)|*.pdf|TPX files (*.tpx)|*.tpx|All files (*.*)|*.*'
  $dialog.Multiselect = $false
  if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    return $dialog.FileName
  }
  return ''
}

function Ask-InputPath($purpose) {
  Write-Host ""
  Write-Host $purpose -ForegroundColor Cyan
  Write-Host "F = choose a project/drawing folder"
  Write-Host "D = choose a PDF/file"
  Write-Host "P = paste a path"
  Write-Host ""
  $mode = Read-Host "Choose F, D, or P"
  switch ($mode.ToUpperInvariant()) {
    "F" { return Normalize-InputPath (Pick-Folder $purpose) }
    "D" { return Normalize-InputPath (Pick-PdfOrFile $purpose) }
    "P" {
      $p = Read-Host "Paste full path"
      return Normalize-InputPath $p
    }
    default {
      Write-Host "Cancelled or invalid choice." -ForegroundColor Yellow
      return ''
    }
  }
}

function Invoke-AgentCommand($description, [string[]]$arguments, $outFolder) {
  New-Item -ItemType Directory -Force -Path $outFolder | Out-Null
  $log = Join-Path $outFolder 'agent_run_log.txt'
  Write-Host ""
  Write-Host "Working: $description" -ForegroundColor Cyan
  Write-Host "Output folder: $outFolder"
  Write-Host "Log: $log"
  Write-Host ""
  Write-Host "This may take a bit on large drawing PDFs or network folders. If it looks quiet, it is still reading the files." -ForegroundColor Yellow
  try {
    $started = Get-Date
    $output = & $python $agent @arguments 2>&1
    $ended = Get-Date
    @(
      "Estimator Agent run"
      "Started: $started"
      "Ended:   $ended"
      "Command: $python $agent $($arguments -join ' ')"
      ""
      "Output:"
      $output
    ) | Set-Content -LiteralPath $log -Encoding UTF8
    Write-Host ""
    Write-Host "Done." -ForegroundColor Green
    return $true
  } catch {
    "ERROR: $($_.Exception.Message)" | Set-Content -LiteralPath $log -Encoding UTF8
    Write-Host ""
    Write-Host "Something went wrong. I opened the output folder/log so you can see what happened." -ForegroundColor Red
    Open-IfExists $outFolder
    Open-IfExists $log -Notepad
    Show-ErrorBox "The agent hit an error. I opened the run log.`n`n$($_.Exception.Message)"
    return $false
  }
}

function Finish-WithReport($title, $outFolder, [string[]]$reportsToOpen) {
  foreach ($report in $reportsToOpen) {
    if (Test-Path -LiteralPath $report) {
      Open-IfExists $report -Notepad
    }
  }
  Open-IfExists $outFolder
  Show-Info $title "Finished. I opened the report and output folder for you."
}

while ($true) {
  Clear-Host
  Write-Host "======================================="
  Write-Host "   Estimator Coworker Agent"
  Write-Host "======================================="
  Write-Host ""
  Write-Host "Main estimator workflow:"
  Write-Host "1. Estimate Project - project folder to estimator review package"
  Write-Host ""
  Write-Host "Support / experimental tools:"
  Write-Host "0. Website-only Accubid prep package - LiveCount web + Accubid workflow"
  Write-Host "2. List item types from drawing or project"
  Write-Host "3. Count a specific item/tag"
  Write-Host "4. Project Intelligence only - classify a project folder"
  Write-Host "5. Drawing Intelligence only - locate sheets and drawing regions"
  Write-Host "17. Symbol Detection only - light fixture candidates"
  Write-Host ""
  Write-Host "Improve / validate the agent:"
  Write-Host "6. Scan Bids 2025 project database"
  Write-Host "7. Open project scan summary"
  Write-Host "8. Build training set from good projects"
  Write-Host "9. Validate training set counts"
  Write-Host "10. Check drawing/spec labels"
  Write-Host "11. Open latest training summary"
  Write-Host ""
  Write-Host "12. Open agent output folder"
  Write-Host ""
  Write-Host "LiveCount integration research:"
  Write-Host "13. Open LiveCount online in controlled browser"
  Write-Host "14. Record LiveCount network while you place one mark"
  Write-Host "15. Place a test circle mark in current LiveCount view"
  Write-Host "16. Audit a LiveCount TPX export"
  Write-Host "Q. Quit"
  Write-Host ""

  $choice = Read-Host "Choose an option"

  switch ($choice.ToUpperInvariant()) {
    "0" {
      $inputPath = Ask-InputPath "Create website-only Accubid prep from a drawing PDF or whole project folder"
      if ([string]::IsNullOrWhiteSpace($inputPath)) { Pause-Agent; continue }
      if (-not (Test-Path -LiteralPath $inputPath)) {
        Show-ErrorBox "That path does not exist:`n$inputPath"
        Pause-Agent
        continue
      }
      $inputName = Split-Path $inputPath -Leaf
      $safeName = Get-SafeName $inputName 'web_accubid_prep'
      $outFolder = Join-Path $coworkerOutRoot "$safeName-web-accubid-prep"
      $ok = Invoke-AgentCommand "creating website-only Accubid prep package" @('web-accubid-prep', '--input', $inputPath, '--out-dir', $outFolder, '--project-name', $inputName) $outFolder
      if ($ok) {
        Finish-WithReport "Website-only Accubid prep complete" $outFolder @(
          (Join-Path $outFolder 'website_accubid_prep_report.md'),
          (Join-Path $outFolder 'LIVECOUNT_WEB_WORKFLOW.md'),
          (Join-Path $outFolder 'takeoff_tasks_for_livecount_web.csv'),
          (Join-Path $outFolder 'accubid_item_mapping_template.csv')
        )
      }
      Pause-Agent
    }
    "1" {
      Write-Host ""
      Write-Host "Estimate Project expects a full project folder, not just one random file." -ForegroundColor Cyan
      $projectFolder = Normalize-InputPath (Pick-Folder "Choose full project folder")
      if ([string]::IsNullOrWhiteSpace($projectFolder)) {
        $projectFolder = Normalize-InputPath (Read-Host "Or paste full project folder path")
      }
      if ([string]::IsNullOrWhiteSpace($projectFolder)) { Pause-Agent; continue }
      if (-not (Test-Path -LiteralPath $projectFolder)) {
        Show-ErrorBox "That project folder does not exist:`n$projectFolder"
        Pause-Agent
        continue
      }
      $projectName = Split-Path $projectFolder -Leaf
      $safeName = Get-SafeName $projectName 'estimate_project'
      $outFolder = Join-Path $coworkerOutRoot "$safeName-estimate-project"
      $ok = Invoke-AgentCommand "running the primary estimator workflow on this project" @('estimate-project', '--project-folder', $projectFolder, '--out-dir', $outFolder, '--project-name', $projectName) $outFolder
      if ($ok) {
        Finish-WithReport "Estimate Project complete" $outFolder @(
          (Join-Path $outFolder 'project_dashboard.md'),
          (Join-Path $outFolder 'takeoff_items.csv'),
          (Join-Path $outFolder 'estimator_review.csv'),
          (Join-Path $outFolder 'accubid_mapping.csv'),
          (Join-Path $outFolder 'validation_answer_key_template.csv'),
          (Join-Path $outFolder 'marked_up_drawings.pdf')
        )
      }
      Pause-Agent
    }
    "2" {
      $inputPath = Ask-InputPath "List item types from a drawing PDF or whole project folder"
      if ([string]::IsNullOrWhiteSpace($inputPath)) { Pause-Agent; continue }
      if (-not (Test-Path -LiteralPath $inputPath)) {
        Show-ErrorBox "That path does not exist:`n$inputPath"
        Pause-Agent
        continue
      }
      $inputName = Split-Path $inputPath -Leaf
      $safeName = Get-SafeName $inputName 'drawing_scan'
      $outFolder = Join-Path $coworkerOutRoot "$safeName-scan"
      $ok = Invoke-AgentCommand "listing candidate item types" @('scan-drawing', '--input', $inputPath, '--out-dir', $outFolder) $outFolder
      if ($ok) {
        Finish-WithReport "Item type scan complete" $outFolder @(
          (Join-Path $outFolder 'drawing_scan_report.md'),
          (Join-Path $outFolder 'item_types.csv')
        )
      }
      Pause-Agent
    }
    "3" {
      $inputPath = Ask-InputPath "Count a specific item/tag in a drawing PDF or project folder"
      if ([string]::IsNullOrWhiteSpace($inputPath)) { Pause-Agent; continue }
      if (-not (Test-Path -LiteralPath $inputPath)) {
        Show-ErrorBox "That path does not exist:`n$inputPath"
        Pause-Agent
        continue
      }
      $item = Read-Host "Item/tag to count, for example EXIT, F1, A1"
      if ([string]::IsNullOrWhiteSpace($item)) { Pause-Agent; continue }
      $inputName = Split-Path $inputPath -Leaf
      $safeName = Get-SafeName $inputName 'drawing_count'
      $outFolder = Join-Path $coworkerOutRoot "$safeName-counts"
      $ok = Invoke-AgentCommand "counting item/tag $item" @('count-item', '--input', $inputPath, '--item', $item, '--out-dir', $outFolder) $outFolder
      if ($ok) {
        $safeItem = ($item.ToUpperInvariant() -replace '[^A-Za-z0-9._-]+', '_').Trim('_')
        Finish-WithReport "Item count complete" $outFolder @(
          (Join-Path $outFolder "count_$safeItem.md"),
          (Join-Path $outFolder "count_$safeItem.csv")
        )
      }
      Pause-Agent
    }
    "4" {
      $projectFolder = Normalize-InputPath (Pick-Folder "Choose project folder containing drawings/specs")
      if ([string]::IsNullOrWhiteSpace($projectFolder)) {
        $projectFolder = Normalize-InputPath (Read-Host "Or paste full project folder path")
      }
      if (-not (Test-Path -LiteralPath $projectFolder)) {
        Show-ErrorBox "That project folder does not exist:`n$projectFolder"
        Pause-Agent
        continue
      }
      $projectName = Split-Path $projectFolder -Leaf
      $safeName = Get-SafeName $projectName 'project_intake'
      $outFolder = Join-Path $workspace "outputs\intake-packets\$safeName"
      $ok = Invoke-AgentCommand "running Project Intelligence on this folder" @('intake-project', '--project-folder', $projectFolder, '--out-dir', $outFolder) $outFolder
      if ($ok) {
        Finish-WithReport "Project Intelligence complete" $outFolder @(
          (Join-Path $outFolder 'project_dashboard.md'),
          (Join-Path $outFolder 'project_files.csv'),
          (Join-Path $outFolder 'electrical_sheet_index.csv')
        )
      }
      Pause-Agent
    }
    "5" {
      $projectFolder = Normalize-InputPath (Pick-Folder "Choose project folder already processed by Project Intelligence")
      if ([string]::IsNullOrWhiteSpace($projectFolder)) {
        $projectFolder = Normalize-InputPath (Read-Host "Or paste full project folder path")
      }
      if (-not (Test-Path -LiteralPath $projectFolder)) {
        Show-ErrorBox "That project folder does not exist:`n$projectFolder"
        Pause-Agent
        continue
      }
      $sheetIndex = Normalize-InputPath (Pick-PdfOrFile "Choose electrical_sheet_index.csv from Project Intelligence")
      if ([string]::IsNullOrWhiteSpace($sheetIndex)) {
        $sheetIndex = Normalize-InputPath (Read-Host "Or paste full path to electrical_sheet_index.csv")
      }
      if (-not (Test-Path -LiteralPath $sheetIndex)) {
        Show-ErrorBox "That sheet index does not exist:`n$sheetIndex"
        Pause-Agent
        continue
      }
      $projectName = Split-Path $projectFolder -Leaf
      $safeName = Get-SafeName $projectName 'drawing_intelligence'
      $outFolder = Join-Path $workspace "outputs\coworker-estimates\$safeName-drawing-intelligence"
      $ok = Invoke-AgentCommand "running Drawing Intelligence on selected sheets" @('drawing-intelligence', '--project-folder', $projectFolder, '--sheet-index', $sheetIndex, '--out-dir', $outFolder) $outFolder
      if ($ok) {
        Finish-WithReport "Drawing Intelligence complete" $outFolder @(
          (Join-Path $outFolder 'drawing_intelligence.md'),
          (Join-Path $outFolder 'sheet_page_map.csv'),
          (Join-Path $outFolder 'drawing_regions.csv')
        )
      }
      Pause-Agent
    }
    "16" {
      $projectName = Read-Host "Project name"
      $tpx = Normalize-InputPath (Pick-PdfOrFile "Choose LiveCount TPX export")
      if ([string]::IsNullOrWhiteSpace($tpx)) {
        $tpx = Normalize-InputPath (Read-Host "Or paste full TPX path")
      }
      if (-not (Test-Path -LiteralPath $tpx)) {
        Show-ErrorBox "That TPX file does not exist:`n$tpx"
        Pause-Agent
        continue
      }
      $outFolder = Join-Path $workspace 'outputs\manual-agent-audits'
      $safeName = Get-SafeName $projectName 'project'
      $out = Join-Path $outFolder "$safeName-agent_review.md"
      $ok = Invoke-AgentCommand "auditing LiveCount TPX export" @('audit-tpx', '--project-name', $projectName, '--tpx', $tpx, '--out', $out) $outFolder
      if ($ok) {
        Finish-WithReport "TPX audit complete" $outFolder @($out)
      }
      Pause-Agent
    }
    "17" {
      $renderedSheets = Normalize-InputPath (Pick-Folder "Choose rendered_sheets folder from Drawing Intelligence")
      if ([string]::IsNullOrWhiteSpace($renderedSheets)) {
        $renderedSheets = Normalize-InputPath (Read-Host "Or paste full rendered_sheets folder path")
      }
      if (-not (Test-Path -LiteralPath $renderedSheets)) {
        Show-ErrorBox "That rendered_sheets folder does not exist:`n$renderedSheets"
        Pause-Agent
        continue
      }
      $safeName = Get-SafeName (Split-Path (Split-Path $renderedSheets -Parent) -Leaf) 'light_fixture_detection'
      $outFolder = Join-Path $workspace "outputs\coworker-estimates\$safeName-light-fixtures"
      $ok = Invoke-AgentCommand "detecting light fixture candidates" @('detect-light-fixtures', '--rendered-sheets-dir', $renderedSheets, '--out-dir', $outFolder) $outFolder
      if ($ok) {
        Finish-WithReport "Light fixture detection complete" $outFolder @(
          (Join-Path $outFolder 'light_fixture_detection.md'),
          (Join-Path $outFolder 'takeoff_items.csv'),
          (Join-Path $outFolder 'estimator_review.csv'),
          (Join-Path $outFolder 'marked_up_drawings.pdf')
        )
      }
      Pause-Agent
    }
    "6" {
      $ok = Invoke-AgentCommand "scanning Bids 2025 project database" @('scan-projects', '--root', $defaultScanRoot, '--out-dir', $defaultScanOut, '--limit', '300', '--max-files-per-project', '3000', '--quiet') $defaultScanOut
      if ($ok) { Finish-WithReport "Database scan complete" $defaultScanOut @("$defaultScanOut\project_scan_summary.md") }
      Pause-Agent
    }
    "7" {
      Open-IfExists "$defaultScanOut\project_scan_summary.md" -Notepad
      Pause-Agent
    }
    "8" {
      $ok = Invoke-AgentCommand "building training set from good projects" @('build-training-set', '--scan-csv', "$defaultScanOut\project_scan.csv", '--out-dir', $trainingOut, '--grades', 'good_training_candidate', '--limit', '10') $trainingOut
      if ($ok) { Finish-WithReport "Training set built" $trainingOut @("$trainingOut\TRAINING_SET_SUMMARY.md") }
      Pause-Agent
    }
    "9" {
      $ok = Invoke-AgentCommand "validating training set counts" @('validate-training-set', '--manifest', "$trainingOut\training_manifest.csv", '--out-dir', "$trainingOut\validation") "$trainingOut\validation"
      if ($ok) { Finish-WithReport "Training validation complete" "$trainingOut\validation" @("$trainingOut\validation\ACCURACY_VALIDATION.md") }
      Pause-Agent
    }
    "10" {
      $ok = Invoke-AgentCommand "checking drawing/spec labels" @('check-drawing-labels', '--manifest', "$trainingOut\training_manifest.csv", '--out-dir', "$trainingOut\drawing-label-check") "$trainingOut\drawing-label-check"
      if ($ok) { Finish-WithReport "Drawing/spec label check complete" "$trainingOut\drawing-label-check" @("$trainingOut\drawing-label-check\DRAWING_LABEL_CHECK.md") }
      Pause-Agent
    }
    "11" {
      Open-IfExists "$trainingOut\TRAINING_SET_SUMMARY.md" -Notepad
      Open-IfExists "$trainingOut\validation\ACCURACY_VALIDATION.md" -Notepad
      Open-IfExists "$trainingOut\drawing-label-check\DRAWING_LABEL_CHECK.md" -Notepad
      Pause-Agent
    }
    "12" {
      Open-IfExists (Join-Path $workspace 'outputs')
      Pause-Agent
    }
    "13" {
      Write-Host ""
      Write-Host "Opening LiveCount in controlled browser mode..." -ForegroundColor Cyan
      & powershell.exe -ExecutionPolicy Bypass -File $appControlBridge -Action open-livecount-online-controlled
      Show-Info "LiveCount controlled browser" "LiveCount should be open now. Log in normally if needed."
      Pause-Agent
    }
    "14" {
      New-Item -ItemType Directory -Force -Path $liveCountControlOut | Out-Null
      Write-Host ""
      Write-Host "Network capture setup" -ForegroundColor Cyan
      Write-Host "Before continuing:"
      Write-Host "1. Open a LiveCount job/sheet in the controlled browser."
      Write-Host "2. Get ready to manually place ONE simple mark, like one EXIT."
      Write-Host "3. After you press Enter here, place the mark during the capture window."
      Write-Host ""
      Read-Host "Press Enter to start a 45-second capture"
      & $node $liveCountBrowserControl --action record-network --seconds 45 --out-dir $liveCountControlOut
      $latestSummary = Get-ChildItem -LiteralPath $liveCountControlOut -Filter 'livecount-network-summary-*.md' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
      if ($latestSummary) {
        Open-IfExists $latestSummary.FullName -Notepad
      }
      Open-IfExists $liveCountControlOut
      Show-Info "LiveCount network capture complete" "I opened the network summary and output folder. Look for POST/PATCH/PUT calls around the mark placement."
      Pause-Agent
    }
    "15" {
      New-Item -ItemType Directory -Force -Path $liveCountControlOut | Out-Null
      Write-Host ""
      Write-Host "This places one small test circle in the currently visible LiveCount sheet." -ForegroundColor Cyan
      $xText = Read-Host "Screen X coordinate, blank for 830"
      $yText = Read-Host "Screen Y coordinate, blank for 300"
      $rText = Read-Host "Screen radius, blank for 10"
      if ([string]::IsNullOrWhiteSpace($xText)) { $xText = "830" }
      if ([string]::IsNullOrWhiteSpace($yText)) { $yText = "300" }
      if ([string]::IsNullOrWhiteSpace($rText)) { $rText = "10" }
      & $node $liveCountBrowserControl --action ui-place-circle --x $xText --y $yText --screen-radius $rText --out-dir $liveCountControlOut
      & $node $liveCountBrowserControl --action screenshot --out-dir $liveCountControlOut
      $latestShot = Get-ChildItem -LiteralPath $liveCountControlOut -Filter 'livecount-screenshot-*.png' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
      if ($latestShot) { Open-IfExists $latestShot.FullName }
      Show-Info "LiveCount mark placed" "I placed a test circle and opened the latest screenshot."
      Pause-Agent
    }
    "Q" {
      break
    }
    default {
      Write-Host "Invalid option." -ForegroundColor Yellow
      Pause-Agent
    }
  }
}
