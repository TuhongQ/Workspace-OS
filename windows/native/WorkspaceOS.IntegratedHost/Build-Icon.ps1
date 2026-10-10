param([string]$OutputPath)
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap 256,256
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = 'AntiAlias'
$g.Clear([System.Drawing.Color]::Transparent)
$shape = New-Object System.Drawing.Drawing2D.GraphicsPath
$shape.AddArc(4,4,72,72,180,90); $shape.AddArc(180,4,72,72,270,90)
$shape.AddArc(180,180,72,72,0,90); $shape.AddArc(4,180,72,72,90,90); $shape.CloseFigure()
$brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush ([System.Drawing.Rectangle]::new(0,0,256,256)),([System.Drawing.ColorTranslator]::FromHtml('#143863')),([System.Drawing.ColorTranslator]::FromHtml('#080E26')),45
$g.FillPath($brush,$shape)
$hex = [System.Drawing.PointF[]]@([System.Drawing.PointF]::new(128,36),[System.Drawing.PointF]::new(207,82),[System.Drawing.PointF]::new(207,174),[System.Drawing.PointF]::new(128,220),[System.Drawing.PointF]::new(49,174),[System.Drawing.PointF]::new(49,82))
$pen = New-Object System.Drawing.Pen ([System.Drawing.ColorTranslator]::FromHtml('#42DDF5')),7
$g.DrawPolygon($pen,$hex)
$line = New-Object System.Drawing.Pen ([System.Drawing.ColorTranslator]::FromHtml('#ECEFFF')),18
$line.StartCap='Round'; $line.EndCap='Round';$line.LineJoin='Round'
$g.DrawLines($line,[System.Drawing.PointF[]]@([System.Drawing.PointF]::new(91,169),[System.Drawing.PointF]::new(91,88),[System.Drawing.PointF]::new(165,169),[System.Drawing.PointF]::new(165,88)))
$ms = New-Object System.IO.MemoryStream
$bmp.Save($ms,[System.Drawing.Imaging.ImageFormat]::Png)
$bytes=$ms.ToArray()
$stream=[System.IO.File]::Create($OutputPath);$writer=New-Object System.IO.BinaryWriter $stream
$writer.Write([uint16]0);$writer.Write([uint16]1);$writer.Write([uint16]1)
$writer.Write([byte]0);$writer.Write([byte]0);$writer.Write([byte]0);$writer.Write([byte]0)
$writer.Write([uint16]1);$writer.Write([uint16]32);$writer.Write([uint32]$bytes.Length);$writer.Write([uint32]22);$writer.Write($bytes);$writer.Dispose()
$bmp.Save([System.IO.Path]::ChangeExtension($OutputPath,'.png'))
$g.Dispose();$bmp.Dispose();$ms.Dispose();$brush.Dispose();$shape.Dispose();$pen.Dispose();$line.Dispose()
