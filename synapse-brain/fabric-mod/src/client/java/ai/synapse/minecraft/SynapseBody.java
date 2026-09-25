package ai.synapse.minecraft;

import baritone.api.BaritoneAPI;
import com.google.gson.JsonObject;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.message.v1.ClientReceiveMessageEvents;
import net.fabricmc.fabric.api.client.rendering.v1.HudRenderCallback;
import net.fabricmc.fabric.api.client.rendering.v1.WorldRenderEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.client.gui.screens.PauseScreen;
import net.minecraft.network.chat.Component;
import net.minecraft.util.FormattedCharSequence;

import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Properties;

/**
 * The body of Synapse in the real Minecraft client.
 *
 * The body only makes things possible: it feels (Senses), sees the game's own picture (Eyes) and can do
 * every player action (Motor). It never decides. Each moment it tells the brain (brain_server.py) what
 * it feels - the same message as the Mineflayer body bot.js - and does what the brain answers.
 * Settings: config/synapse_body.properties (brain address, pace, picture size, hands off).
 */
public final class SynapseBody implements ClientModInitializer {
    static final Properties CFG = new Properties();
    private static volatile boolean paused;
    private static boolean handsOff = true;
    private static boolean listening;
    static volatile JsonObject hud;
    static volatile String said = "";
    static volatile String doing = "—";
    static volatile String link = "ищу мозг…";

    @Override
    public void onInitializeClient() {
        loadConfig();
        handsOff = Boolean.parseBoolean(CFG.getProperty("hands_off", "true"));
        try {
            var s = BaritoneAPI.getSettings();
            s.freeLook.value = false;          // the head turns where the body walks: the eyes see the way
            s.allowParkour.value = false;       // as in bot.js: plain walking, climbing and digging
            s.chatControl.value = false;        // nobody gives Synapse orders through Baritone's chat commands
            s.logAsToast.value = false;
            s.chatDebug.value = false;
        } catch (Throwable ignored) {
        }
        ClientTickEvents.END_CLIENT_TICK.register(SynapseBody::tick);
        WorldRenderEvents.END.register(context -> Eyes.afterWorld(Minecraft.getInstance()));
        HudRenderCallback.EVENT.register((graphics, delta) -> renderHud(graphics));
        ClientReceiveMessageEvents.CHAT.register((message, signed, sender, params, receivedAt) -> {
            Minecraft mc = Minecraft.getInstance();
            boolean self = mc.player != null && sender != null && mc.player.getUUID().equals(sender.getId());
            if (!self && sender != null) Senses.heard(sender.getName(), message.getString());
        });
        ClientReceiveMessageEvents.GAME.register((message, overlay) -> {
            if (!overlay) Senses.gameMessage(message);
        });
        Thread t = new Thread(new BrainLink(), "synapse-brain-link");
        t.setDaemon(true);
        t.start();
    }

    private static void loadConfig() {
        Path path = FabricLoader.getInstance().getConfigDir().resolve("synapse_body.properties");
        CFG.setProperty("brain_host", "127.0.0.1");
        CFG.setProperty("brain_port", "5555");
        CFG.setProperty("step_ms", "100");
        CFG.setProperty("frame", "256");
        CFG.setProperty("zones", "8");
        CFG.setProperty("hands_off", "true");
        try {
            if (Files.exists(path)) {
                try (Reader r = Files.newBufferedReader(path, StandardCharsets.UTF_8)) { CFG.load(r); }
            } else {
                Files.createDirectories(path.getParent());
                try (Writer w = Files.newBufferedWriter(path, StandardCharsets.UTF_8)) {
                    CFG.store(w, "Synapse body: brain address, pace (ms between moments), picture size the eyes send, "
                        + "hands_off=true blocks the physical keyboard and mouse (Esc still pauses)");
                }
            }
        } catch (IOException error) {
            System.err.println("[Synapse] config: " + error.getMessage());
        }
        String port = System.getenv("SYNAPSE_BRAIN_PORT");
        if (port != null && !port.isBlank()) CFG.setProperty("brain_port", port.trim());
    }

    public static boolean handsOff() { return handsOff; }

    public static boolean paused() { return paused; }

    static boolean inWorld(Minecraft mc) {
        return mc.player != null && mc.level != null && mc.getConnection() != null && mc.getCurrentServer() != null;
    }

    static volatile long clientTicks;                        // the client's own ticks (to check it keeps the world's pace)

    private static void tick(Minecraft mc) {
        clientTicks++;
        if (mc.options != null && mc.options.pauseOnLostFocus) {
            mc.options.pauseOnLostFocus = false;      // Synapse lives on when the window is not in focus
            mc.options.save();
        }
        if (mc.screen instanceof PauseScreen) paused = true;
        else if (mc.screen == null) paused = false;
        if (!listening && mc.getSoundManager() != null) {  // the ears: every sound the game plays
            mc.getSoundManager().addListener((sound, events, range) -> Senses.heardSound(sound));
            listening = true;
        }
        if (!inWorld(mc)) return;
        if (mc.player.getHealth() <= 0.0F) {          // death: the brain hears it with the next moment
            Motor.stop(mc);
            Senses.onDeath(mc);
            return;
        }
        Senses.tick(mc);
        if (paused) {
            Motor.stop(mc);
            return;
        }
        Motor.tick(mc);
    }

    private static void renderHud(GuiGraphics g) {
        Minecraft mc = Minecraft.getInstance();
        if (mc.player == null || mc.options.hideGui) return;
        JsonObject h = hud;
        List<Component> rows = new ArrayList<>();
        String name = h != null && h.has("name") ? h.get("name").getAsString() : "Synapse";
        rows.add(Component.literal("§b§l" + name + (paused ? "  §eПАУЗА" : "")));
        if (h != null) {
            String lived = h.has("lived") ? h.get("lived").getAsString() : String.valueOf(h.get("age").getAsInt());
            rows.add(Component.literal("§7прожил §f" + lived + " §7· §f" + h.get("stage").getAsString()));
            rows.add(Component.literal("§7чувствую: §d" + h.get("feeling").getAsString()));
            String goal = h.get("goal").getAsString();
            if (!goal.isEmpty()) rows.add(Component.literal("§7хочу: §e" + goal));
        }
        rows.add(Component.literal("§7делаю: §6" + doing));
        if (!said.isEmpty()) rows.add(Component.literal("§7сказал: §f" + said));
        rows.add(Component.literal("§8" + link));
        int width = 260;
        int x = Math.max(8, mc.getWindow().getGuiScaledWidth() - width - 10);
        int y = 10;
        List<FormattedCharSequence> lines = new ArrayList<>();
        for (Component row : rows) lines.addAll(mc.font.split(row, width - 12));
        int height = lines.size() * 10 + 10;
        g.fill(x - 6, y - 5, x + width, y + height, 0xA0101418);
        g.fill(x - 6, y - 5, x - 4, y + height, 0xFF35D6C8);
        for (FormattedCharSequence line : lines) {
            g.drawString(mc.font, line, x, y, 0xFFFFFFFF, true);
            y += 10;
        }
    }
}
