param(
  [ValidateSet('scan','launch-accubid','launch-livecount-desktop','open-livecount-online-controlled','menu','click-menu')]
  [string]$Action = 'scan',

  [int]$Handle = 0,
  [string]$MenuPath = '',
  [string]$LiveCountUrl = 'https://livecount.trimble.com'
)

$ErrorActionPreference = 'Stop'

$AccubidPro16 = 'C:\Program Files (x86)\Trimble\Classic 16\AccuPro.exe'
$LiveCountPro5 = 'C:\Program Files (x86)\Trimble\LiveCount\LiveCount 5\LiveCountPro.exe'
$Edge = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
$Chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$ControlledBrowserProfile = 'C:\Users\namid\Documents\Codex\2026-06-22\is\outputs\controlled-livecount-browser'

Add-Type @"
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

public static class WinCtl {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll")]
    public static extern int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr GetMenu(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern int GetMenuItemCount(IntPtr hMenu);

    [DllImport("user32.dll")]
    public static extern IntPtr GetSubMenu(IntPtr hMenu, int nPos);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetMenuString(IntPtr hMenu, uint uIDItem, StringBuilder lpString, int cchMax, uint flags);

    [DllImport("user32.dll")]
    public static extern uint GetMenuItemID(IntPtr hMenu, int nPos);

    [DllImport("user32.dll")]
    public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
}
"@

function Get-TopWindows {
  $windows = New-Object System.Collections.Generic.List[object]
  $callback = [WinCtl+EnumWindowsProc]{
    param([IntPtr]$hWnd, [IntPtr]$lParam)
    if (-not [WinCtl]::IsWindowVisible($hWnd)) { return $true }
    $len = [WinCtl]::GetWindowTextLength($hWnd)
    if ($len -le 0) { return $true }
    $sb = New-Object System.Text.StringBuilder ($len + 1)
    [void][WinCtl]::GetWindowText($hWnd, $sb, $sb.Capacity)
    $pidRaw = 0
    [void][WinCtl]::GetWindowThreadProcessId($hWnd, [ref]$pidRaw)
    $processName = ''
    try { $processName = (Get-Process -Id $pidRaw -ErrorAction Stop).ProcessName } catch {}
    $windows.Add([pscustomobject]@{
      Handle = $hWnd.ToInt64()
      ProcessId = $pidRaw
      ProcessName = $processName
      Title = $sb.ToString()
    })
    return $true
  }
  [void][WinCtl]::EnumWindows($callback, [IntPtr]::Zero)
  $windows
}

function Walk-Menu {
  param(
    [IntPtr]$Menu,
    [string]$Prefix = ''
  )
  $count = [WinCtl]::GetMenuItemCount($Menu)
  for ($index = 0; $index -lt $count; $index++) {
    $builder = New-Object System.Text.StringBuilder 512
    [void][WinCtl]::GetMenuString($Menu, [uint32]$index, $builder, $builder.Capacity, 0x400)
    $text = $builder.ToString().Replace('&', '').Trim()
    if ([string]::IsNullOrWhiteSpace($text)) { $text = "<separator-$index>" }
    $id = [WinCtl]::GetMenuItemID($Menu, $index)
    $path = if ($Prefix) { "$Prefix > $text" } else { $text }
    [pscustomobject]@{ Path = $path; CommandId = $id; Index = $index }
    $submenu = [WinCtl]::GetSubMenu($Menu, $index)
    if ($submenu -ne [IntPtr]::Zero) {
      Walk-Menu -Menu $submenu -Prefix $path
    }
  }
}

function Find-MenuItem {
  param(
    [IntPtr]$Menu,
    [string[]]$Parts,
    [int]$Depth = 0,
    [string]$Prefix = ''
  )
  $count = [WinCtl]::GetMenuItemCount($Menu)
  for ($index = 0; $index -lt $count; $index++) {
    $builder = New-Object System.Text.StringBuilder 512
    [void][WinCtl]::GetMenuString($Menu, [uint32]$index, $builder, $builder.Capacity, 0x400)
    $text = $builder.ToString().Replace('&', '').Trim()
    if ($text -ne $Parts[$Depth]) { continue }
    $path = if ($Prefix) { "$Prefix > $text" } else { $text }
    if ($Depth -eq ($Parts.Count - 1)) {
      return [pscustomobject]@{ Path = $path; CommandId = [WinCtl]::GetMenuItemID($Menu, $index) }
    }
    $submenu = [WinCtl]::GetSubMenu($Menu, $index)
    if ($submenu -ne [IntPtr]::Zero) {
      $found = Find-MenuItem -Menu $submenu -Parts $Parts -Depth ($Depth + 1) -Prefix $path
      if ($null -ne $found) { return $found }
    }
  }
  return $null
}

switch ($Action) {
  'scan' {
    Get-TopWindows |
      Where-Object {
        $_.ProcessName -match 'Accu|LiveCount|chrome|msedge' -or
        $_.Title -match 'Accubid|LiveCount|Trimble'
      } |
      Sort-Object ProcessName,Title |
      Format-Table -AutoSize
  }
  'launch-accubid' {
    if (-not (Test-Path -LiteralPath $AccubidPro16)) { throw "Accubid Pro 16 not found at $AccubidPro16" }
    Start-Process -FilePath $AccubidPro16
    Write-Host "Started Accubid Pro 16."
  }
  'launch-livecount-desktop' {
    if (-not (Test-Path -LiteralPath $LiveCountPro5)) { throw "LiveCount Pro 5 not found at $LiveCountPro5" }
    Start-Process -FilePath $LiveCountPro5
    Write-Host "Started LiveCount Pro 5."
  }
  'open-livecount-online-controlled' {
    New-Item -ItemType Directory -Force -Path $ControlledBrowserProfile | Out-Null
    if (Test-Path -LiteralPath $Edge) {
      Start-Process -FilePath $Edge -ArgumentList @(
        '--remote-debugging-port=9222',
        "--user-data-dir=$ControlledBrowserProfile",
        $LiveCountUrl
      )
      Write-Host "Opened LiveCount online in a controllable Edge browser profile."
      Write-Host "Profile: $ControlledBrowserProfile"
      Write-Host "Control port: 9222"
    } elseif (Test-Path -LiteralPath $Chrome) {
      Start-Process -FilePath $Chrome -ArgumentList @(
        '--remote-debugging-port=9222',
        "--user-data-dir=$ControlledBrowserProfile",
        $LiveCountUrl
      )
      Write-Host "Opened LiveCount online in a controllable Chrome browser profile."
      Write-Host "Profile: $ControlledBrowserProfile"
      Write-Host "Control port: 9222"
    } else {
      throw "Neither Edge nor Chrome was found."
    }
  }
  'menu' {
    if ($Handle -eq 0) { throw "Pass -Handle from the scan output." }
    $menu = [WinCtl]::GetMenu([IntPtr]$Handle)
    if ($menu -eq [IntPtr]::Zero) { throw "No classic Windows menu found for handle $Handle." }
    Walk-Menu -Menu $menu | Format-Table -AutoSize
  }
  'click-menu' {
    if ($Handle -eq 0) { throw "Pass -Handle from the scan output." }
    if ([string]::IsNullOrWhiteSpace($MenuPath)) { throw "Pass -MenuPath like 'File > Open'." }
    $menu = [WinCtl]::GetMenu([IntPtr]$Handle)
    if ($menu -eq [IntPtr]::Zero) { throw "No classic Windows menu found for handle $Handle." }
    $parts = $MenuPath -split '\s*>\s*'
    $found = Find-MenuItem -Menu $menu -Parts $parts
    if ($null -eq $found) { throw "Menu path not found: $MenuPath" }
    if ($found.CommandId -eq 4294967295) { throw "Menu path is a submenu, not a clickable command: $MenuPath" }
    [void][WinCtl]::SetForegroundWindow([IntPtr]$Handle)
    [void][WinCtl]::SendMessage([IntPtr]$Handle, 0x0111, [IntPtr]([int]$found.CommandId), [IntPtr]::Zero)
    Write-Host "Sent menu command: $($found.Path) [$($found.CommandId)]"
  }
}
