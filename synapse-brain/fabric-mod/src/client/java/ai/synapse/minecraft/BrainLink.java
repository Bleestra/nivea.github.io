package ai.synapse.minecraft;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.minecraft.client.Minecraft;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;

/**
 * The nerve between body and brain: one JSON line up (what I feel and see), one line down (what to do).
 * The same protocol as bot.js, so brain_server.py serves either body unchanged.
 */
final class BrainLink implements Runnable {
    @Override
    public void run() {
        Minecraft mc = Minecraft.getInstance();
        String host = SynapseBody.CFG.getProperty("brain_host", "127.0.0.1");
        int port = Integer.parseInt(SynapseBody.CFG.getProperty("brain_port", "5555").trim());
        long stepMs = Long.parseLong(SynapseBody.CFG.getProperty("step_ms", "100").trim());
        int frame = Integer.parseInt(SynapseBody.CFG.getProperty("frame", "256").trim());
        while (true) {
            try (Socket socket = new Socket()) {
                socket.connect(new InetSocketAddress(host, port), 3000);
                socket.setTcpNoDelay(true);
                BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8));
                Writer out = new OutputStreamWriter(socket.getOutputStream(), StandardCharsets.UTF_8);
                SynapseBody.link = "мозг на связи · " + host + ":" + port;
                System.out.println("[Synapse] the brain is here: " + host + ":" + port);
                long[] pace = new long[5];               // ms of the last moment: eyes, senses, brain, action, wait
                long lastWall = 0, lastTick = -1;
                while (true) {
                    long t0 = System.nanoTime();
                    waitUntilReady(mc);
                    long t1 = System.nanoTime();
                    byte[] seen = frame > 0 ? Eyes.look(frame) : null;
                    long t2 = System.nanoTime();
                    JsonObject m = onClient(mc, () -> Senses.observe(mc)).get(5, TimeUnit.SECONDS);
                    long t3 = System.nanoTime();
                    JsonObject p = new JsonObject();       // where the time of a moment goes (for the dashboard)
                    p.addProperty("eyes_ms", (t2 - t1) / 1_000_000);
                    p.addProperty("senses_ms", (t3 - t2) / 1_000_000);
                    p.addProperty("brain_ms", pace[2]);
                    p.addProperty("act_ms", pace[3]);
                    p.addProperty("wait_ms", (t1 - t0) / 1_000_000 + pace[4]);
                    long tick = SynapseBody.clientTicks, wall = System.currentTimeMillis();   // MY ticks, not the server's clock
                    if (lastTick >= 0 && wall > lastWall) p.addProperty("ticks_per_s", Math.round((tick - lastTick) * 1000.0 / (wall - lastWall)));
                    lastTick = tick;
                    lastWall = wall;
                    m.add("pace", p);
                    if (seen != null) {
                        m.addProperty("frame", Base64.getEncoder().encodeToString(seen));
                        var wh = new com.google.gson.JsonArray();
                        wh.add(frame);
                        wh.add(frame);
                        m.add("frame_wh", wh);
                    }
                    m.addProperty("want_hud", true);
                    long t4 = System.nanoTime();
                    out.write(m.toString());
                    out.write('\n');
                    out.flush();
                    String line = in.readLine();
                    if (line == null) break;
                    long t5 = System.nanoTime();
                    pace[2] = (t5 - t4) / 1_000_000;
                    JsonObject reply = JsonParser.parseString(line).getAsJsonObject();
                    CompletableFuture<Void> done = onClient(mc, () -> Motor.start(mc, reply)).get(5, TimeUnit.SECONDS);
                    try {
                        done.get(60, TimeUnit.SECONDS);      // the motor has its own timeouts (digging up to 30 s); a safety net
                    } catch (Exception ignored) {
                        mc.execute(() -> Motor.stop(mc));
                    }
                    long t6 = System.nanoTime();
                    pace[3] = (t6 - t5) / 1_000_000;
                    Thread.sleep(stepMs);
                    pace[4] = (System.nanoTime() - t6) / 1_000_000;
                }
            } catch (InterruptedException error) {
                return;
            } catch (Exception error) {
                SynapseBody.link = "жду мозг на " + host + ":" + port;
            }
            try { Thread.sleep(3000); } catch (InterruptedException error) { return; }
        }
    }

    /** A moment starts when the body is in the world, awake, not paused and not in the middle of an action. */
    private static void waitUntilReady(Minecraft mc) throws InterruptedException {
        while (!SynapseBody.inWorld(mc) || SynapseBody.paused() || Motor.busy()
            || mc.player == null || mc.player.getHealth() <= 0.0F) {
            Thread.sleep(20);
        }
    }

    private static <T> CompletableFuture<T> onClient(Minecraft mc, Supplier<T> work) {
        CompletableFuture<T> result = new CompletableFuture<>();
        mc.execute(() -> {
            try { result.complete(work.get()); }
            catch (Throwable error) { result.completeExceptionally(error); }
        });
        return result;
    }
}
