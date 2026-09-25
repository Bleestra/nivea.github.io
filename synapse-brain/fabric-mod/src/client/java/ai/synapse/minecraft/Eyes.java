package ai.synapse.minecraft;

import com.mojang.blaze3d.platform.NativeImage;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Screenshot;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

/**
 * The eyes: the game's own first-person picture, taken right after the world is drawn and before the
 * HUD and the hand, so the brain sees the world and not our overlay. Sent as a square of BGR bytes
 * (the centre of the view, averaged down to size x size), the format vision/ expects.
 */
final class Eyes {
    private static volatile CompletableFuture<byte[]> wanted;
    private static volatile int wantedSize;

    private Eyes() {}

    /** Called from the brain link: ask for the next picture and wait for it (null if none comes). */
    static byte[] look(int size) {
        CompletableFuture<byte[]> f = new CompletableFuture<>();
        wantedSize = size;
        wanted = f;
        try {
            return f.get(1, TimeUnit.SECONDS);      // a minimised window draws nothing: then no picture
        } catch (Exception error) {
            wanted = null;
            return null;
        }
    }

    /** WorldRenderEvents.END, on the render thread: the world is in the frame buffer, the HUD not yet. */
    static void afterWorld(Minecraft mc) {
        CompletableFuture<byte[]> f = wanted;
        if (f == null) return;
        wanted = null;
        try (NativeImage image = Screenshot.takeScreenshot(mc.getMainRenderTarget())) {
            f.complete(square(image.getPixels(), image.getWidth(), image.getHeight(), wantedSize));
        } catch (Throwable error) {
            f.complete(null);
        }
    }

    /** ARGB pixels (w x h) -> the centre square averaged down to n x n, as BGR bytes (row by row). */
    static byte[] square(int[] argb, int w, int h, int n) {
        int side = Math.min(w, h);
        int x0 = (w - side) / 2;
        int y0 = (h - side) / 2;
        byte[] out = new byte[n * n * 3];
        for (int j = 0; j < n; j++) {
            int ya = y0 + j * side / n, yb = Math.max(ya + 1, y0 + (j + 1) * side / n);
            for (int i = 0; i < n; i++) {
                int xa = x0 + i * side / n, xb = Math.max(xa + 1, x0 + (i + 1) * side / n);
                long r = 0, g = 0, b = 0;
                int count = 0;
                for (int y = ya; y < yb; y++) {
                    int row = y * w;
                    for (int x = xa; x < xb; x++) {
                        int p = argb[row + x];
                        r += (p >> 16) & 0xFF;
                        g += (p >> 8) & 0xFF;
                        b += p & 0xFF;
                        count++;
                    }
                }
                int o = (j * n + i) * 3;
                out[o] = (byte) (b / count);
                out[o + 1] = (byte) (g / count);
                out[o + 2] = (byte) (r / count);
            }
        }
        return out;
    }
}
