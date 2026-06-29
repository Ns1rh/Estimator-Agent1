param(
    [Parameter(Mandatory = $true)]
    [int]$Handle
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class MenuNative {
    [DllImport("user32.dll")]
    public static extern IntPtr GetMenu(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern int GetMenuItemCount(IntPtr hMenu);

    [DllImport("user32.dll")]
    public static extern IntPtr GetSubMenu(IntPtr hMenu, int nPos);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetMenuString(
        IntPtr hMenu,
        uint uIDItem,
        StringBuilder lpString,
        int cchMax,
        uint flags
    );

    [DllImport("user32.dll")]
    public static extern uint GetMenuItemID(IntPtr hMenu, int nPos);
}
"@

function Walk-Menu {
    param(
        [IntPtr]$Menu,
        [string]$Prefix = ""
    )

    $count = [MenuNative]::GetMenuItemCount($Menu)
    for ($index = 0; $index -lt $count; $index++) {
        $builder = New-Object System.Text.StringBuilder 512
        [void][MenuNative]::GetMenuString($Menu, [uint32]$index, $builder, $builder.Capacity, 0x400)
        $text = $builder.ToString().Replace("&", "")
        $id = [MenuNative]::GetMenuItemID($Menu, $index)
        $path = if ($Prefix) { "$Prefix > $text" } else { $text }
        [pscustomobject]@{ Path = $path; CommandId = $id }

        $submenu = [MenuNative]::GetSubMenu($Menu, $index)
        if ($submenu -ne [IntPtr]::Zero) {
            Walk-Menu -Menu $submenu -Prefix $path
        }
    }
}

$menu = [MenuNative]::GetMenu([IntPtr]$Handle)
if ($menu -eq [IntPtr]::Zero) {
    throw "No menu found for window handle $Handle"
}

Walk-Menu -Menu $menu
