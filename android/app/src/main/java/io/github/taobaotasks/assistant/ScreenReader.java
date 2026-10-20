package io.github.taobaotasks.assistant;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.hardware.HardwareBuffer;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.WindowManager;
import com.google.android.gms.tasks.Tasks;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.Text;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions;
import java.nio.ByteBuffer;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** Offline OCR fallback. All bitmaps and recognized window contents stay in memory. */
final class ScreenReader implements AutoCloseable {
    private final AutomationService service;
    private final TextRecognizer recognizer = TextRecognition.getClient(new ChineseTextRecognizerOptions.Builder().build());
    private MediaProjection projection;
    private VirtualDisplay display;
    private ImageReader images;
    private volatile boolean closed;
    private int projectionWidth, projectionHeight;

    ScreenReader(AutomationService service, int result, Intent consent) {
        this.service = service;
        if (Build.VERSION.SDK_INT < 30) {
            if (consent == null) throw new IllegalArgumentException("capture consent missing");
            projection = service.getSystemService(MediaProjectionManager.class).getMediaProjection(result, consent);
            projection.registerCallback(new MediaProjection.Callback() {
                @Override public void onStop() { if (!closed) service.projectionEnded(); }
            }, new Handler(Looper.getMainLooper()));
            DisplayMetrics metrics = metrics(); projectionWidth = metrics.widthPixels; projectionHeight = metrics.heightPixels;
            images = ImageReader.newInstance(projectionWidth, projectionHeight, PixelFormat.RGBA_8888, 2);
            display = projection.createVirtualDisplay("TaskScreen", projectionWidth, projectionHeight, metrics.densityDpi,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, images.getSurface(), null, null);
        }
    }
    static DisplayMetrics metrics(AutomationService service) {
        DisplayMetrics metrics = new DisplayMetrics();
        service.getSystemService(WindowManager.class).getDefaultDisplay().getRealMetrics(metrics); return metrics;
    }
    private DisplayMetrics metrics() { return metrics(service); }

    Frame read(Frame nativeFrame) throws Exception {
        service.check();
        Bitmap bitmap = capture();
        com.google.android.gms.tasks.Task<Text> pending = null;
        try {
            if (bitmap.getWidth() > bitmap.getHeight()) throw new TaskRunner.Stop("请将手机转为竖屏后重新开始");
            pending = recognizer.process(InputImage.fromBitmap(bitmap, 0));
            Text text = Tasks.await(pending, 10, TimeUnit.SECONDS);
            service.check();
            Frame result = new Frame(nativeFrame.pkg, bitmap.getWidth(), bitmap.getHeight(), true);
            for (Text.TextBlock block : text.getTextBlocks()) for (Text.Line line : block.getLines()) {
                Rect box = line.getBoundingBox(); if (box == null) continue;
                String label = line.getText().replaceAll("\\s+", "");
                addLine(result, label, box);
            }
            // A race button inferred from pixels must be bright yellow, carry the full label,
            // and appear with a readable balance. Dimmed content under a modal is excluded.
            Frame.Node race = result.exact("升级赛车拿钱");
            if (race != null && (TaskRules.energy(result.text()) < 0 || !yellow(bitmap, race))) result.nodes.remove(race);
            if (result.nodes.isEmpty()) throw new TaskRunner.Stop("截图未识别到文字，请确认活动页面可见");
            return result;
        } finally {
            if (pending != null && !pending.isComplete()) pending.addOnCompleteListener(service.getMainExecutor(), ignored -> bitmap.recycle());
            else bitmap.recycle();
        }
    }
    private static void addLine(Frame frame, String label, Rect box) {
        for (String button : new String[]{"去完成", "已完成", "立即领取"}) {
            if (label.endsWith(button) && !label.equals(button)) {
                int split = box.right - Math.round(box.width() * button.length() / (float)label.length());
                frame.nodes.add(node(label.substring(0, label.length()-button.length()), new Rect(box.left, box.top, split, box.bottom)));
                frame.nodes.add(node(button, new Rect(split, box.top, box.right, box.bottom))); return;
            }
        }
        frame.nodes.add(node(label, box));
    }
    private static Frame.Node node(String text, Rect box) {
        return new Frame.Node(text, "", "", "", -1, box.left, box.top, box.right, box.bottom, false, false);
    }
    private static boolean yellow(Bitmap bitmap, Frame.Node label) {
        int left = Math.max(0, label.left - bitmap.getWidth()/12), right = Math.min(bitmap.getWidth()-1,label.right + bitmap.getWidth()/12);
        int top = Math.max(0,label.top - bitmap.getHeight()/80), bottom = Math.min(bitmap.getHeight()-1,label.bottom + bitmap.getHeight()/50);
        int count = 0, matches = 0;
        for (int y = top; y < bottom; y += 5) for (int x = left; x < right; x += 5) {
            int pixel = bitmap.getPixel(x,y); count++;
            if (Color.red(pixel) > 180 && Color.green(pixel) > 140 && Color.blue(pixel) < 130) matches++;
        }
        return count > 0 && matches > count*.5;
    }
    private Bitmap capture() throws Exception {
        if (closed) throw new InterruptedException();
        if (Build.VERSION.SDK_INT >= 30) return accessibilityScreenshot();
        DisplayMetrics size = metrics();
        if (size.widthPixels != projectionWidth || size.heightPixels != projectionHeight) throw new TaskRunner.Stop("屏幕方向改变，请保持竖屏并重新开始");
        long end = android.os.SystemClock.elapsedRealtime() + 4000;
        while (!closed && android.os.SystemClock.elapsedRealtime() < end) {
            service.check();
            Image image;
            synchronized (this) { image = images == null ? null : images.acquireLatestImage(); }
            if (image != null) {
                try {
                    Image.Plane plane = image.getPlanes()[0]; ByteBuffer buffer = plane.getBuffer();
                    int pixelStride = plane.getPixelStride(), rowStride = plane.getRowStride();
                    if (pixelStride != 4) throw new TaskRunner.Stop("设备截图格式不支持");
                    Bitmap padded = Bitmap.createBitmap(rowStride/pixelStride, image.getHeight(), Bitmap.Config.ARGB_8888);
                    padded.copyPixelsFromBuffer(buffer);
                    Bitmap crop = Bitmap.createBitmap(padded,0,0,image.getWidth(),image.getHeight());
                    if (crop != padded) padded.recycle(); return crop;
                } finally { image.close(); }
            }
            service.pause(100);
        }
        throw new TaskRunner.Stop("屏幕截图超时，请重新开始并允许屏幕识别");
    }
    @androidx.annotation.RequiresApi(30)
    private Bitmap accessibilityScreenshot() throws Exception {
        CompletableFuture<Bitmap> future = new CompletableFuture<>(); AtomicBoolean abandoned = new AtomicBoolean();
        service.takeScreenshot(Display.DEFAULT_DISPLAY, service.getMainExecutor(), new AccessibilityService.TakeScreenshotCallback() {
            @Override public void onSuccess(AccessibilityService.ScreenshotResult result) {
                HardwareBuffer buffer = result.getHardwareBuffer(); Bitmap hardware = null, copy = null;
                try {
                    hardware = Bitmap.wrapHardwareBuffer(buffer, result.getColorSpace());
                    if (hardware != null) copy = hardware.copy(Bitmap.Config.ARGB_8888, false);
                    if (copy == null) { future.completeExceptionally(new TaskRunner.Stop("截图内容不可读取")); return; }
                    synchronized (future) {
                        if (closed || abandoned.get() || !future.complete(copy)) copy.recycle();
                    }
                } finally { if (hardware != null) hardware.recycle(); buffer.close(); }
            }
            @Override public void onFailure(int error) {
                future.completeExceptionally(new TaskRunner.Stop("无障碍截图失败（"+error+"），请重新开启服务"));
            }
        });
        boolean delivered = false;
        try { Bitmap bitmap = future.get(8, TimeUnit.SECONDS); delivered = true; return bitmap; }
        catch (java.util.concurrent.ExecutionException failure) {
            if (failure.getCause() instanceof TaskRunner.Stop) throw (TaskRunner.Stop)failure.getCause();
            throw failure;
        }
        finally {
            synchronized (future) {
                abandoned.set(true);
                if (!delivered && future.isDone() && !future.isCompletedExceptionally()) {
                    Bitmap unused = future.getNow(null); if (unused != null) unused.recycle();
                }
            }
        }
    }
    @Override public synchronized void close() {
        closed = true;
        if (display != null) { display.release(); display = null; }
        if (images != null) { images.close(); images = null; }
        if (projection != null) { projection.stop(); projection = null; }
        recognizer.close();
    }
}
