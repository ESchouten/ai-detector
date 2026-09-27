using System.Drawing;
using System.Drawing.Text;

namespace AIDetector.Desktop;

internal static class MenuIcon
{
    // Use the icons supplied by Windows 11.
    public static Bitmap Create(string glyph)
    {
        var image = new Bitmap(32, 32);
        using var graphics = Graphics.FromImage(image);
        using var font = new Font("Segoe Fluent Icons", 24, FontStyle.Regular, GraphicsUnit.Pixel);
        using var brush = new SolidBrush(SystemColors.MenuText);
        using var format = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };
        graphics.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
        graphics.DrawString(glyph, font, brush, new RectangleF(0, 0, 32, 32), format);
        return image;
    }
}
