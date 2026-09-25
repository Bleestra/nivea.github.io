package ai.synapse.minecraft;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.contents.TranslatableContents;
import net.minecraft.tags.FluidTags;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.MobCategory;
import net.minecraft.world.entity.TamableAnimal;
import net.minecraft.world.entity.decoration.ArmorStand;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * What the body feels, in the same words as bot.js: the 5x5 cells ahead, touch all around, the sky,
 * creatures by kind, what happened to beings nearby, what became of the blocks I placed, what people
 * say, advancements and deaths. Plain facts only - which of them matter, the brain learns.
 */
public final class Senses {
    static final int[][] DIRS = {{0, -1}, {1, 0}, {0, 1}, {-1, 0}};   // N E S W as (dx, dz)
    static final float[] YAW = {180F, -90F, 0F, 90F};                // Minecraft yaw facing N E S W
    static int heading = -1;          // 0..3, set from the body's yaw at the first moment
    static int pitch = 0;             // -1 up, 0 level, 1 down
    static boolean sprint, sneak;
    static int step;

    static final Set<String> everHeld = new HashSet<>();
    private static final Set<String> advancements = new HashSet<>();
    private static final List<String[]> newAdvancements = Collections.synchronizedList(new ArrayList<>());
    private static final List<String[]> heard = Collections.synchronizedList(new ArrayList<>());
    private static volatile String deathMsg = "";
    private static boolean died, respawnRequested;

    static final Set<Integer> mine = new HashSet<>();                // animals I tamed
    static int lastHit = -1;
    static final Map<BlockPos, String> built = new HashMap<>();     // blocks I placed myself
    static final Set<BlockPos> dugByMe = new HashSet<>();
    private static final Map<Integer, float[]> beings = new HashMap<>();  // id -> {hurtTime, dead, health}

    // what happened since the last moment (bot.js feelEv)
    private static final JsonArray evDeaths = new JsonArray(), evHurt = new JsonArray(), evLost = new JsonArray();
    private static volatile boolean boom, gift;
    private static Integer tamed;
    private static String carerDid;
    static String ate, traded, read;
    /** A chest I just had open: where it is and everything in it ({"at": [x, y, z], "items": {...}}). */
    static volatile JsonObject chest;
    static JsonArray trades = new JsonArray();

    /** Other Synapses in the same world (SYNAPSE_PEERS): players, but not the caregiver. */
    static final Set<String> PEERS = new HashSet<>();
    private static final List<String[]> peersSaid = Collections.synchronizedList(new ArrayList<>());
    private static final List<Object[]> sounds = Collections.synchronizedList(new ArrayList<>());
    static int visGrid() {                                 // the picture is taught in n x n zones (config "zones")
        return Integer.parseInt(SynapseBody.CFG.getProperty("zones", "8").trim());
    }

    static {
        String peers = System.getenv("SYNAPSE_PEERS");
        if (peers != null) for (String p : peers.split(",")) if (!p.isBlank()) PEERS.add(p.trim());
    }

    private static final ArrayDeque<Vec3> trail = new ArrayDeque<>();
    private static int seenAt = -99;
    private static JsonArray seenCache = new JsonArray();
    private static float lastHealth = 20;
    private static int lastLogs, lastStone, lastNear = 9;
    private static boolean canCraftNew, canCraftGear;
    private static volatile Vec3 boomAt;

    private Senses() {}

    // ------------------------------------------------------------------ events from the game
    static void heard(String user, String text) {
        if (PEERS.contains(user)) peersSaid.add(new String[]{user, text});   // another Synapse, not a person
        else heard.add(new String[]{user, text});
    }

    /** Hearing: every sound the game plays near me (what a player hears through the speakers). */
    static void heardSound(net.minecraft.client.resources.sounds.SoundInstance s) {
        if (s == null || s.isRelative() || s.getLocation() == null) return;
        String[] id = s.getLocation().getPath().split("\\.");
        String what;
        if (id.length >= 2 && id[0].equals("entity")) what = id[1].equals("generic") && id.length > 2 ? id[2] : id[1];
        else if (id.length >= 2 && id[0].equals("ambient") && id[1].equals("cave")) what = "cave";
        else return;                                       // footsteps, blocks, music: too many, too little meaning
        if (sounds.size() < 64) sounds.add(new Object[]{what, s.getX(), s.getY(), s.getZ(), id.length > 2 ? id[id.length - 1] : ""});
    }

    public static void heardExplosion(Vec3 where) { boomAt = where; boom = true; }

    public static void pickedUp(int playerId) {
        Minecraft mc = Minecraft.getInstance();
        LocalPlayer p = mc.player;
        if (p == null || playerId != p.getId()) return;
        if (nearestPlayer(mc, 5) != null) gift = true;   // picked something up while a person stood by: a gift
    }

    /** System messages: my advancements (by their id, whatever the client's language) and my death. */
    static void gameMessage(Component message) {
        Minecraft mc = Minecraft.getInstance();
        if (mc.player == null || !(message.getContents() instanceof TranslatableContents t)) return;
        Object[] args = t.getArgs();
        String me = mc.player.getGameProfile().getName();
        if (args.length == 0 || !text(args[0]).equals(me)) return;
        if (t.getKey().startsWith("chat.type.advancement.") && args.length > 1) {
            String title = text(args[1]).replaceAll("^\\[|]$", "");
            String id = advancementId(args[1]);
            advancements.add(title);
            newAdvancements.add(new String[]{id != null ? id : title, title});
        } else if (t.getKey().startsWith("death.")) {
            String s = message.getString();
            deathMsg = s.startsWith(me + " ") ? s.substring(me.length() + 1) : s;
        }
    }

    private static String text(Object o) { return o instanceof Component c ? c.getString() : String.valueOf(o); }

    /** "advancements.story.mine_stone.title" -> "story/mine_stone" (the id the reference book uses). */
    private static String advancementId(Object arg) {
        if (!(arg instanceof Component c)) return null;
        ArrayDeque<Component> todo = new ArrayDeque<>();
        todo.add(c);
        while (!todo.isEmpty()) {
            Component x = todo.poll();
            if (x.getContents() instanceof TranslatableContents t) {
                String k = t.getKey();
                if (k.startsWith("advancements.") && k.endsWith(".title")) {
                    String[] p = k.substring("advancements.".length(), k.length() - ".title".length()).split("\\.", 2);
                    return p.length == 2 ? p[0] + "/" + p[1] : null;
                }
                for (Object a : t.getArgs()) if (a instanceof Component ac) todo.add(ac);
            }
            todo.addAll(x.getSiblings());
        }
        return null;
    }

    static void onDeath(Minecraft mc) {
        if (respawnRequested) return;
        respawnRequested = true;
        died = true;
        mc.player.respawn();                              // a new body; the brain and memory stay
        mc.setScreen(null);
    }

    /** Things my hands did (a block broken or placed, a hit, a window opened...): the efference counter. */
    static int deeds;

    static void dug(BlockPos pos) { dugByMe.add(pos.immutable()); deeds++; }

    // ------------------------------------------------------------------ pain, and watching others
    private static final JsonArray evPain = new JsonArray();
    private static final JsonArray evWatched = new JsonArray();
    private static final Map<BlockPos, Object[]> othersBreaking = new HashMap<>();   // pos -> {player id, block, time}
    private static final Set<Integer> eating = new HashSet<>();

    /** The game's own damage report: [what kind of pain (fall, mob_attack, starve, drown, lava...), who, which]. */
    public static void damaged(int entityId, String type, int causeId) {
        Minecraft mc = Minecraft.getInstance();
        LocalPlayer p = mc.player;
        if (p == null || mc.level == null) return;
        Entity cause = causeId >= 0 ? mc.level.getEntity(causeId) : null;
        if (entityId == p.getId()) {
            JsonArray x = new JsonArray();
            x.add(type);
            x.add(cause == null ? "" : String.valueOf(kindOf(cause)));
            x.add(cause == null ? "" : cause instanceof Player pl ? pl.getGameProfile().getName()
                : BuiltInRegistries.ENTITY_TYPE.getKey(cause.getType()).getPath());
            if (evPain.size() < 16) evPain.add(x);
        } else if (cause instanceof Player pl && pl != p) {            // I saw someone hit a being
            Entity victim = mc.level.getEntity(entityId);
            if (victim != null) {                                       // by kind, as my own blows are felt
                String k = kindOf(victim);
                watched(pl, "attacked", k != null ? k : BuiltInRegistries.ENTITY_TYPE.getKey(victim.getType()).getPath());
            }
        }
    }

    public static void othersBreaking(int breakerId, BlockPos pos, int progress) {
        Minecraft mc = Minecraft.getInstance();
        if (mc.player == null || mc.level == null || breakerId == mc.player.getId()) return;
        if (progress >= 0 && progress <= 9) {
            othersBreaking.put(pos.immutable(), new Object[]{breakerId, name(mc.level.getBlockState(pos)), mc.level.getGameTime()});
        }
    }

    public static void blockChanging(BlockPos pos, BlockState now) {
        Minecraft mc = Minecraft.getInstance();
        if (mc.player == null || mc.level == null) return;
        BlockState old = mc.level.getBlockState(pos);
        if (!old.isAir() && now.isAir()) {                          // broken: by whom I saw breaking it
            Object[] b = othersBreaking.remove(pos);
            if (b != null && mc.level.getGameTime() - (long) b[2] < 100 && mc.level.getEntity((int) b[0]) instanceof Player pl) {
                watched(pl, "broke", name(old));
            }
        } else if (old.canBeReplaced() && !now.isAir() && !now.canBeReplaced() && !built.containsKey(pos)) {
            Player who = null;                                      // placed: the one next to it who just moved a hand
            double best = 5.5;
            for (Player pl : mc.level.players()) {
                if (pl == mc.player) continue;
                double d = pl.position().distanceTo(Vec3.atCenterOf(pos));
                if (d < best && (pl.swinging || pl.swingTime > 0)) { best = d; who = pl; }
            }
            if (who != null) watched(who, "placed", name(now));
        }
    }

    /** What I saw a person (or another Synapse) do: [who kind, name, act, what, what was in their hand]. */
    private static void watched(Player pl, String act, String what) {
        Minecraft mc = Minecraft.getInstance();
        if (mc.player == null || pl.distanceTo(mc.player) > 24 || evWatched.size() >= 16) return;
        JsonArray w = new JsonArray();
        w.add(String.valueOf(kindOf(pl)));
        w.add(pl.getGameProfile().getName());
        w.add(act);
        w.add(what);
        w.add(Hands.key(pl.getMainHandItem()));
        evWatched.add(w);
    }

    /** I broke a block: remember what I carried, and a second later feel what it gave me (maybe nothing). */
    private static final List<Object[]> breaking = new ArrayList<>();          // {block, counts before, game time}
    private static final JsonArray evBroke = new JsonArray();

    static void broke(Minecraft mc, String block) {
        breaking.add(new Object[]{block, counts(mc.player), mc.level.getGameTime()});
    }

    private static Map<String, Integer> counts(LocalPlayer p) {
        Map<String, Integer> c = new HashMap<>();
        for (ItemStack s : p.getInventory().items) if (!s.isEmpty()) c.merge(Hands.key(s), s.getCount(), Integer::sum);
        return c;
    }

    static void placed(BlockPos pos, String name) { built.put(pos.immutable(), name); deeds++; }

    /** Every tick: what happens to the beings and blocks around me (the brain gets it with the next moment). */
    static void tick(Minecraft mc) {
        LocalPlayer p = mc.player;
        respawnRequested = false;
        if (!breaking.isEmpty()) {                            // a dropped thing is picked up within a second
            var it = breaking.iterator();
            while (it.hasNext()) {
                Object[] b = it.next();
                if (mc.level.getGameTime() - (long) b[2] < 25) continue;
                @SuppressWarnings("unchecked") Map<String, Integer> before = (Map<String, Integer>) b[1];
                JsonArray got = new JsonArray();
                counts(p).forEach((k, n) -> { if (n > before.getOrDefault(k, 0)) got.add(k); });
                JsonArray x = new JsonArray();
                x.add((String) b[0]);
                x.add(got);
                evBroke.add(x);
                it.remove();
            }
        }
        if (mc.level.getGameTime() % 2 != 0) return;
        Set<Integer> alive = new HashSet<>();
        for (Entity e : mc.level.entitiesForRendering()) {
            if (!(e instanceof LivingEntity le) || e == p) continue;
            String kind = kindOf(e);
            if (kind == null) continue;
            double d = e.distanceTo(p);
            alive.add(e.getId());
            float hp = le.getHealth();
            float[] st = beings.computeIfAbsent(e.getId(), k -> new float[]{0, 0, hp});
            float lost = Math.max(0F, st[2] - hp);                      // how much it was hurt: a fist 1, a sword 4-7
            boolean flinched = le.hurtTime > 0 && st[0] == 0;
            if ((flinched || lost > 0.01F) && d <= 12) {                // (the health may arrive a tick after the flinch)
                JsonArray h = new JsonArray();
                h.add(kind); h.add(e.getId()); h.add(Math.round(lost * 10F) / 10F); h.add(lastHit == e.getId() ? "self" : "");
                evHurt.add(h);
            }
            st[0] = le.hurtTime;
            st[2] = hp;
            if (le.isDeadOrDying() && st[1] == 0) {
                st[1] = 1;
                if (d <= 16) {                                          // ... and whether it fell by my hand
                    JsonArray x = new JsonArray();
                    x.add(kind); x.add(e.getId()); x.add(mine.contains(e.getId())); x.add(lastHit == e.getId() ? "self" : ""); x.add(d <= 12);
                    evDeaths.add(x);
                }
                Player carer = nearestPlayerTo(mc, e.position(), 4);
                if (carer != null && (kind.equals("zombie") || kind.equals("hostile") || kind.equals("creeper"))) carerDid = "killed";
            }
            if (e instanceof TamableAnimal ta && ta.isOwnedBy(p) && mine.add(e.getId())) tamed = e.getId();
        }
        beings.keySet().retainAll(alive);
        for (Player pl : mc.level.players()) {                  // someone eats: I see it (and may want to try)
            if (pl == p) continue;
            if (pl.isUsingItem() && Hands.isFood(pl.getUseItem())) {
                if (eating.add(pl.getId())) watched(pl, "ate", Hands.key(pl.getUseItem()));
            } else {
                eating.remove(pl.getId());
            }
        }
        othersBreaking.values().removeIf(b -> mc.level.getGameTime() - (long) b[2] > 200);
        if (!built.isEmpty()) {                           // a block I placed is gone, and not because I dug it
            var it = built.entrySet().iterator();
            while (it.hasNext()) {
                var kv = it.next();
                if (!mc.level.hasChunkAt(kv.getKey())) continue;
                String now = name(mc.level.getBlockState(kv.getKey()));
                if (!now.equals(kv.getValue())) {
                    if (!dugByMe.remove(kv.getKey())) {
                        JsonArray l = new JsonArray();
                        l.add(kv.getKey().getX()); l.add(kv.getKey().getZ()); l.add(kv.getValue());
                        evLost.add(l);
                    }
                    it.remove();
                }
            }
        }
        if (dugByMe.size() > 256) dugByMe.clear();
    }

    // ------------------------------------------------------------------ the moment's report (bot.js ask())
    static JsonObject observe(Minecraft mc) {
        LocalPlayer p = mc.player;
        if (heading < 0) heading = Math.floorMod(Math.round(((p.getYRot() - 180F) / 90F)), 4);
        boolean done = died;
        float[] rl = reward(mc);
        if (step % 20 == 0) {
            canCraftNew = !Hands.craftable(mc, Hands.newThings(mc)).isEmpty();
            canCraftGear = !Hands.craftable(mc, Hands.GEAR).isEmpty();
        }
        Vec3 pos = p.position();
        JsonObject m = new JsonObject();
        m.add("obs", ints(observeGrid(mc)));
        m.addProperty("inv", (int) rl[1]);
        m.addProperty("goal", goal(mc));
        m.addProperty("reward", done ? rl[0] - 1 : rl[0]);
        m.addProperty("done", done);
        m.addProperty("n_actions", Motor.ACTIONS.length);
        m.add("items", inventory(p));
        int free = 0;                                     // the inventory grid a player sees: how many slots are empty
        for (ItemStack s : p.getInventory().items) if (s.isEmpty()) free++;
        m.addProperty("free_slots", free);
        m.addProperty("table_near", Hands.tableNear(mc) != null);   // a crafting table within reach (mine or anyone's)
        JsonArray chunk = new JsonArray();
        chunk.add(Math.floorDiv((int) Math.floor(pos.x), 16));
        chunk.add(Math.floorDiv((int) Math.floor(pos.z), 16));
        m.add("chunk", chunk);
        m.addProperty("food", p.getFoodData().getFoodLevel());
        m.addProperty("health", p.getHealth());
        m.addProperty("can_craft_new", canCraftNew);
        m.add("feat", ints(features(mc)));
        m.addProperty("died", done ? deathMsg : "");
        m.addProperty("sky", seesSky(mc) ? 1 : 0);
        m.add("around", ints(around(mc)));
        m.addProperty("stuck", stuck(p) ? 1 : 0);
        m.addProperty("y", (int) Math.floor(pos.y));
        m.add("near", nearList(mc));
        m.add("fev", takeFeelings());
        m.addProperty("sleeping", p.isSleeping());
        m.addProperty("dim", mc.level.dimension().location().getPath());
        m.addProperty("time", mc.level.getDayTime() % 24000L);
        m.addProperty("heading", heading);
        m.addProperty("pitch", pitch);
        JsonArray look = new JsonArray();                  // where exactly the head points (degrees)
        look.add(Math.round(p.getYRot() * 10) / 10.0);
        look.add(Math.round(p.getXRot() * 10) / 10.0);
        m.add("look", look);
        JsonArray xz = new JsonArray();
        xz.add((int) Math.floor(pos.x));
        xz.add((int) Math.floor(pos.z));
        m.add("xz", xz);
        ItemStack held = p.getMainHandItem();
        m.addProperty("held", held.isEmpty() ? "" : Hands.key(held));
        m.addProperty("diamond_seen", oreSeen(mc));
        m.add("seen", seenThings(mc));
        Player carer = nearestPlayer(mc, 8);
        if (carer != null && !carer.getMainHandItem().isEmpty()) m.addProperty("carer_holds", Hands.key(carer.getMainHandItem()));
        m.add("heard", drain(heard));
        m.add("advancements", drain(newAdvancements));
        JsonArray craftable = new JsonArray();
        for (Hands.Craft c : Hands.craftable(mc, null)) craftable.add(c.name());
        m.add("craftable", craftable);                    // the recipe book shows what I can make now
        m.add("hear", hearing(mc));
        m.add("peers_said", drain(peersSaid));
        m.add("near_vis", inView(mc));
        JsonArray at = new JsonArray();                          // exactly where I am (the sense of place)
        at.add(Math.round(pos.x * 100) / 100.0);
        at.add(Math.round(pos.y * 100) / 100.0);
        at.add(Math.round(pos.z * 100) / 100.0);
        m.add("pos", at);
        m.addProperty("fov", mc.options.fov().get());
        m.addProperty("client_ticks", SynapseBody.clientTicks);   // my own lived ticks (age in game time)
        BlockPos eyes = p.blockPosition().above();               // how light it is where my eyes are (0 dark .. 15)
        m.addProperty("light", mc.level.getRawBrightness(eyes, mc.level.getSkyDarken()));
        m.add("pain", evPain.deepCopy());                        // what hurt me since the last moment, and who
        while (!evPain.isEmpty()) evPain.remove(0);
        m.add("watched", evWatched.deepCopy());                  // what I saw people do
        while (!evWatched.isEmpty()) evWatched.remove(0);
        JsonObject act = Motor.lastResult;                       // did my last action do anything?
        if (act != null) { m.add("act", act); Motor.lastResult = null; }
        if (Integer.parseInt(SynapseBody.CFG.getProperty("frame", "128").trim()) > 0) {
            m.add("vis_labels", visLabels(mc, visGrid()));  // what is really in each zone of the picture: the eyes' teacher
        }
        died = false;
        deathMsg = "";
        step++;
        return m;
    }

    // ------------------------------------------------------------------ the senses themselves
    static String name(BlockState s) {
        return s.isAir() ? "air" : BuiltInRegistries.BLOCK.getKey(s.getBlock()).getPath();
    }

    /** 0 passable, 1 trunk, 2 stone, 3 lava, 4 water, 5 wall - as bot.js blockClass. */
    static int blockClass(Minecraft mc, BlockPos pos) {
        if (!mc.level.hasChunkAt(pos)) return 5;
        BlockState s = mc.level.getBlockState(pos);
        String n = name(s);
        if (s.getFluidState().is(FluidTags.LAVA) || n.contains("lava")) return 3;
        if (s.getFluidState().is(FluidTags.WATER) || n.contains("water")) return 4;
        if (n.endsWith("_log") || n.endsWith("_wood")) return 1;
        if (n.equals("stone") || n.contains("ore") || n.equals("cobblestone") || n.equals("deepslate")) return 2;
        if (s.getCollisionShape(mc.level, pos).isEmpty()) return 0;
        return 5;
    }

    private static int[] observeGrid(Minecraft mc) {
        BlockPos p = mc.player.blockPosition();
        int[] f = DIRS[heading], r = DIRS[(heading + 1) % 4];
        int[] obs = new int[25];
        int k = 0;
        for (int a = 0; a < 5; a++) {
            for (int b = -2; b <= 2; b++) {
                int dx = f[0] * a + r[0] * b, dz = f[1] * a + r[1] * b;
                int feet = blockClass(mc, p.offset(dx, 0, dz));
                int head = blockClass(mc, p.offset(dx, 1, dz));
                int above = blockClass(mc, p.offset(dx, 2, dz));
                int c;
                if (feet == 1 || head == 1) c = 1;
                else if (feet == 3 || head == 3) c = 3;
                else if (feet == 4) c = 4;
                else if (feet == 2 || head == 2) c = 2;
                else if (head == 0 && (feet == 0 || above == 0)) c = 0;
                else c = 5;
                obs[k++] = c;
            }
        }
        return obs;
    }

    static boolean solid(Minecraft mc, BlockPos pos) {
        BlockState s = mc.level.getBlockState(pos);
        return !s.getCollisionShape(mc.level, pos).isEmpty() && !name(s).contains("leaves");
    }

    private static boolean seesSky(Minecraft mc) {         // nothing solid above the head (leaves let light through)
        BlockPos p = mc.player.blockPosition();
        for (int dy = 2; dy < 64; dy++) {
            BlockPos q = p.above(dy);
            if (!mc.level.hasChunkAt(q) || q.getY() >= mc.level.getMaxY()) break;
            if (solid(mc, q)) return false;
        }
        return true;
    }

    private static int[] around(Minecraft mc) {             // touch: every side, above the head and under the feet
        BlockPos p = mc.player.blockPosition();
        int[] out = new int[6];
        for (int k = 0; k < 4; k++) {
            int[] f = DIRS[(heading + k) % 4];
            out[k] = blockClass(mc, p.offset(f[0], 0, f[1])) * 6 + blockClass(mc, p.offset(f[0], 1, f[1]));
        }
        out[4] = blockClass(mc, p.above(2));
        out[5] = blockClass(mc, p.below());
        return out;
    }

    private static boolean stuck(LocalPlayer p) {            // the feeling of being stuck: not moved in 12 moments
        Vec3 now = p.position();
        trail.addLast(now);
        if (trail.size() > 12) trail.removeFirst();
        if (trail.size() < 12) return false;
        double far = 0;
        for (Vec3 q : trail) far = Math.max(far, q.distanceTo(now));
        return far < 1.5;
    }

    /** Direction (1 ahead, 2 right, 3 behind, 4 left) and distance bucket (0..3), as bot.js relDir. */
    static int relDir(Minecraft mc, double x, double z) {
        Vec3 p = mc.player.position();
        double dx = x - p.x, dz = z - p.z;
        int[] f = DIRS[heading], r = DIRS[(heading + 1) % 4];
        double ahead = dx * f[0] + dz * f[1], right = dx * r[0] + dz * r[1];
        int dir = Math.abs(ahead) >= Math.abs(right) ? (ahead > 0 ? 1 : 3) : (right > 0 ? 2 : 4);
        double dist = Math.abs(dx) + Math.abs(dz);
        return dir * 4 + (dist <= 2 ? 0 : dist <= 5 ? 1 : dist <= 12 ? 2 : 3);
    }

    private static int goal(Minecraft mc) {                  // far vision: the nearest log at my height
        BlockPos p = mc.player.blockPosition();
        BlockPos best = null;
        double bd = Double.MAX_VALUE;
        for (int dy = -1; dy <= 1; dy++) {
            for (int dx = -32; dx <= 32; dx++) {
                for (int dz = -32; dz <= 32; dz++) {
                    BlockPos q = p.offset(dx, dy, dz);
                    double d = dx * dx + dz * dz + dy * dy;
                    if (d >= bd || d > 32 * 32) continue;
                    if (name(mc.level.getBlockState(q)).endsWith("_log")) { best = q; bd = d; }
                }
            }
        }
        return best == null ? 0 : relDir(mc, best.getX() + 0.5, best.getZ() + 0.5);
    }

    private static int[] features(Minecraft mc) {
        LocalPlayer p = mc.player;
        Entity hostile = nearestEntity(mc, 24, e -> e.getType().getCategory() == MobCategory.MONSTER);
        Entity animal = nearestEntity(mc, 24, e -> e.getType().getCategory() == MobCategory.CREATURE);
        int armor = 0;
        for (ItemStack s : p.getInventory().armor) if (!s.isEmpty()) armor++;
        int pick = 0;
        for (ItemStack s : p.getInventory().items) if (Hands.key(s).endsWith("_pickaxe")) pick = Math.max(pick, Hands.tier(Hands.key(s)));
        long t = mc.level.getDayTime() % 24000L;
        return new int[]{hostile == null ? 0 : relDir(mc, hostile.getX(), hostile.getZ()),
            animal == null ? 0 : relDir(mc, animal.getX(), animal.getZ()),
            Math.min(4, (int) (p.getHealth() / 5)), Math.min(4, p.getFoodData().getFoodLevel() / 5), armor,
            Hands.heldClass(p), pick, t > 13000 && t < 23000 ? 1 : 0, sprint ? 1 : 0, sneak ? 1 : 0, pitch + 1,
            canCraftGear ? 1 : 0, Math.min(15, advancements.size())};
    }

    private static JsonObject inventory(LocalPlayer p) {
        Map<String, Integer> inv = new LinkedHashMap<>();
        for (ItemStack s : p.getInventory().items) {
            if (s.isEmpty()) continue;
            String k = Hands.key(s);
            inv.merge(k, s.getCount(), Integer::sum);
            everHeld.add(k);
        }
        for (ItemStack s : p.getInventory().offhand) if (!s.isEmpty()) inv.merge(Hands.key(s), s.getCount(), Integer::sum);
        for (ItemStack s : p.getInventory().armor) if (!s.isEmpty()) inv.put("worn:" + Hands.key(s), 1);
        JsonObject o = new JsonObject();
        inv.forEach(o::addProperty);
        return o;
    }

    /** Who is around, by kind - as a child tells a cat from a zombie. */
    static String kindOf(Entity e) {
        if (e == null || e instanceof ArmorStand) return null;
        if (e instanceof Player pl) return PEERS.contains(pl.getGameProfile().getName()) ? "peer" : "carer";
        String n = BuiltInRegistries.ENTITY_TYPE.getKey(e.getType()).getPath();
        if (n.equals("creeper")) return "creeper";
        if (n.equals("villager") || n.equals("wandering_trader")) return "villager";
        if (n.equals("iron_golem")) return "golem";
        if (n.contains("zombie") || n.equals("husk") || n.equals("drowned")) return "zombie";
        if (n.equals("cat") || n.equals("ocelot") || n.equals("wolf") || n.equals("parrot")) return mine.contains(e.getId()) ? "mycat" : "cat";
        MobCategory c = e.getType().getCategory();
        if (c == MobCategory.MONSTER) return "hostile";
        if (c == MobCategory.CREATURE) return "animal";
        return null;
    }

    private static JsonArray nearList(Minecraft mc) {
        JsonArray out = new JsonArray();
        for (Entity e : mc.level.entitiesForRendering()) {
            if (e == mc.player) continue;
            String k = kindOf(e);
            if (k == null) continue;
            int d = (int) Math.floor(e.distanceTo(mc.player));
            if (d > 8) continue;
            JsonArray x = new JsonArray();
            x.add(k); x.add(e.getId()); x.add(d);
            out.add(x);
        }
        return out;
    }

    /** The eye cannot see through walls: a ray from the eyes must reach this block first. */
    static boolean visible(Minecraft mc, BlockPos b) {
        Vec3 eye = mc.player.getEyePosition();
        if (Vec3.atCenterOf(b).distanceTo(mc.player.position()) < 2.5) return true;
        double[][] offs = {{0.5, 0.5, 0.5}, {0.5, 0.95, 0.5}, {0.5, 0.05, 0.5}};
        for (double[] o : offs) {
            Vec3 c = new Vec3(b.getX() + o[0], b.getY() + o[1], b.getZ() + o[2]);
            Vec3 end = eye.add(c.subtract(eye).normalize().scale(c.distanceTo(eye) + 0.5));
            BlockHitResult hit = mc.level.clip(new ClipContext(eye, end, ClipContext.Block.OUTLINE, ClipContext.Fluid.NONE, mc.player));
            if (hit.getType() == HitResult.Type.BLOCK && hit.getBlockPos().equals(b)) return true;
        }
        return false;
    }

    /** Nearest visible block of each kind within 12, and creatures within 16: [name, distance, block|mob]. */
    private static JsonArray seenThings(Minecraft mc) {
        if (step - seenAt < 5) return seenCache;
        BlockPos p = mc.player.blockPosition();
        List<BlockPos> blocks = new ArrayList<>();
        for (BlockPos q : BlockPos.betweenClosed(p.offset(-12, -12, -12), p.offset(12, 12, 12))) {
            if (q.distSqr(p) > 144 || !mc.level.hasChunkAt(q)) continue;
            if (!mc.level.getBlockState(q).isAir()) blocks.add(q.immutable());
        }
        blocks.sort(Comparator.comparingDouble(q -> q.distSqr(p)));
        Map<String, Integer> found = new LinkedHashMap<>();
        Map<String, double[]> where = new HashMap<>();          // where I saw it (for the memory of places)
        Set<String> isBlock = new HashSet<>();
        int checked = 0;
        for (BlockPos q : blocks) {
            if (checked >= 600) break;
            checked++;
            String n = name(mc.level.getBlockState(q));
            if (found.containsKey(n) || !visible(mc, q)) continue;
            found.put(n, (int) Math.floor(Math.sqrt(q.distSqr(p))));
            where.put(n, new double[]{q.getX(), q.getY(), q.getZ()});
            isBlock.add(n);
        }
        for (Entity e : mc.level.entitiesForRendering()) {
            if (e == mc.player) continue;
            double d = e.distanceTo(mc.player);
            String n = BuiltInRegistries.ENTITY_TYPE.getKey(e.getType()).getPath();
            if (d < 16 && (!found.containsKey(n) || found.get(n) > d)) {
                found.put(n, (int) Math.floor(d));
                where.put(n, new double[]{Math.floor(e.getX()), Math.floor(e.getY()), Math.floor(e.getZ())});
            }
        }
        JsonArray out = new JsonArray();
        found.forEach((n, d) -> {
            JsonArray x = new JsonArray();
            x.add(n); x.add(d); x.add(isBlock.contains(n) ? "block" : "mob");
            double[] w = where.get(n);
            if (w != null) { x.add((int) w[0]); x.add((int) w[1]); x.add((int) w[2]); }
            out.add(x);
        });
        seenAt = step;
        seenCache = out;
        return out;
    }

    /** Nearest visible block with this name within 16 (for the motor programs aimed by attention). */
    static BlockPos nearestSeenBlock(Minecraft mc, String name) {
        BlockPos p = mc.player.blockPosition();
        List<BlockPos> hits = new ArrayList<>();
        for (BlockPos q : BlockPos.betweenClosed(p.offset(-16, -16, -16), p.offset(16, 16, 16))) {
            if (q.distSqr(p) <= 256 && mc.level.hasChunkAt(q) && name(mc.level.getBlockState(q)).equals(name)) hits.add(q.immutable());
        }
        hits.sort(Comparator.comparingDouble(q -> q.distSqr(p)));
        for (int i = 0; i < Math.min(40, hits.size()); i++) if (visible(mc, hits.get(i))) return hits.get(i);
        return null;
    }

    private static int oreSeen(Minecraft mc) {               // a diamond ore my eyes can actually see
        BlockPos p = mc.player.blockPosition();
        for (BlockPos q : BlockPos.betweenClosed(p.offset(-8, -8, -8), p.offset(8, 8, 8))) {
            String n = name(mc.level.getBlockState(q));
            if ((n.equals("diamond_ore") || n.equals("deepslate_diamond_ore")) && visible(mc, q.immutable())) {
                return relDir(mc, q.getX() + 0.5, q.getZ() + 0.5);
            }
        }
        return 0;
    }

    static Entity nearestEntity(Minecraft mc, double max, java.util.function.Predicate<Entity> pred) {
        Entity best = null;
        double bd = max;
        for (Entity e : mc.level.entitiesForRendering()) {
            if (e == mc.player || !e.isAlive() || !pred.test(e)) continue;
            double d = e.distanceTo(mc.player);
            if (d < bd) { bd = d; best = e; }
        }
        return best;
    }

    static Player nearestPlayer(Minecraft mc, double max) {
        return (Player) nearestEntity(mc, max, e -> e instanceof Player);
    }

    private static Player nearestPlayerTo(Minecraft mc, Vec3 at, double max) {
        for (Player pl : mc.level.players()) if (pl != mc.player && pl.position().distanceTo(at) < max) return pl;
        return null;
    }

    private static int count(LocalPlayer p, Pattern name) {
        int n = 0;
        for (ItemStack s : p.getInventory().items) if (!s.isEmpty() && name.matcher(Hands.key(s)).find()) n += s.getCount();
        return n;
    }

    private static final Pattern LOGS = Pattern.compile("_log$"), STONE = Pattern.compile("^(cobblestone|stone)$");

    /** The old shaped reward of bot.js (used only when the brain runs without --self). Returns {r, logs}. */
    private static float[] reward(Minecraft mc) {
        LocalPlayer p = mc.player;
        int logs = count(p, LOGS), stone = count(p, STONE);
        float r = -0.01F + Math.max(0, logs - lastLogs) + Math.max(0, stone - lastStone) * 0.3F;
        int[] obs = observeGrid(mc);
        int near = 9;
        for (int i = 0; i < 25; i++) if (obs[i] == 1) near = Math.min(near, i / 5 + Math.abs(i % 5 - 2));
        if (near < lastNear) r += 0.05F;
        else if (near > lastNear && lastNear < 9) r -= 0.05F;
        lastNear = near;
        if (p.getHealth() < lastHealth) r -= 1.0F;
        lastLogs = logs;
        lastStone = stone;
        lastHealth = p.getHealth();
        return new float[]{r, logs};
    }

    private static JsonObject takeFeelings() {
        JsonObject e = new JsonObject();
        e.add("deaths", evDeaths.deepCopy());
        e.add("hurt", evHurt.deepCopy());
        e.add("lost", evLost.deepCopy());
        e.add("broke", evBroke.deepCopy());                   // [block, [what it gave me]] - maybe nothing
        while (!evBroke.isEmpty()) evBroke.remove(0);
        e.addProperty("boom", boom && boomAt != null && boomAt.distanceTo(Minecraft.getInstance().player.position()) < 24);
        e.addProperty("gift", gift);
        if (tamed != null) e.addProperty("tamed", tamed);
        if (carerDid != null) e.addProperty("carerDid", carerDid);
        if (ate != null) e.addProperty("ate", ate);
        e.add("trades", trades);
        if (traded != null) e.addProperty("traded", traded);
        if (read != null) e.addProperty("read", read);
        JsonObject c = chest;
        if (c != null) { e.add("chest", c); chest = null; }
        while (!evDeaths.isEmpty()) evDeaths.remove(0);
        while (!evHurt.isEmpty()) evHurt.remove(0);
        while (!evLost.isEmpty()) evLost.remove(0);
        boom = gift = false;
        tamed = null;
        carerDid = ate = traded = read = null;
        trades = new JsonArray();
        return e;
    }

    private static JsonArray drain(List<String[]> list) {
        JsonArray out = new JsonArray();
        synchronized (list) {
            for (String[] x : list) {
                JsonArray a = new JsonArray();
                for (String s : x) a.add(s);
                out.add(a);
            }
            list.clear();
        }
        return out;
    }

    private static JsonArray ints(int[] xs) {
        JsonArray a = new JsonArray();
        for (int x : xs) a.add(x);
        return a;
    }

    static AABB around(Vec3 c, double r) { return new AABB(c.x - r, c.y - r, c.z - r, c.x + r, c.y + r, c.z + r); }

    /** Sounds since the last moment: [what, direction (relDir), distance, which sound]. */
    private static JsonArray hearing(Minecraft mc) {
        JsonArray out = new JsonArray();
        synchronized (sounds) {
            for (Object[] s : sounds) {
                double x = (double) s[1], y = (double) s[2], z = (double) s[3];
                double d = mc.player.position().distanceTo(new Vec3(x, y, z));
                if (d > 24) continue;
                JsonArray a = new JsonArray();
                a.add((String) s[0]); a.add(relDir(mc, x, z)); a.add((int) Math.floor(d)); a.add((String) s[4]);
                out.add(a);
            }
            sounds.clear();
        }
        return out;
    }

    /** Ids of the beings near me that are in my field of view and not behind a wall. */
    private static JsonArray inView(Minecraft mc) {
        JsonArray out = new JsonArray();
        LocalPlayer p = mc.player;
        Vec3 f = Vec3.directionFromRotation(p.getXRot(), p.getYRot());
        double cos = Math.cos(Math.toRadians(mc.options.fov().get() * 0.75));
        for (Entity e : mc.level.entitiesForRendering()) {
            if (e == p || kindOf(e) == null || e.distanceTo(p) > 16) continue;
            Vec3 to = e.getEyePosition().subtract(p.getEyePosition()).normalize();
            if (to.dot(f) >= cos && p.hasLineOfSight(e)) out.add(e.getId());
        }
        return out;
    }

    /**
     * The eyes' teacher: a ray through the centre of each of the n x n zones of the picture the eyes get
     * (the centre square of the view), and what it hits first - [name, distance, block|mob|item|sky].
     * The brain only learns from it; in the human-senses mode it never acts on it.
     */
    static JsonArray visLabels(Minecraft mc, int n) {
        LocalPlayer p = mc.player;
        Vec3 eye = mc.gameRenderer.getMainCamera().getPosition();
        Vec3 f = Vec3.directionFromRotation(p.getXRot(), p.getYRot());
        Vec3 right = f.cross(new Vec3(0, 1, 0));
        if (right.lengthSqr() < 1e-6) {
            double yaw = Math.toRadians(p.getYRot());
            right = new Vec3(-Math.cos(yaw), 0, -Math.sin(yaw));
        }
        right = right.normalize();
        Vec3 up = right.cross(f).normalize();
        double t = Math.tan(Math.toRadians(mc.options.fov().get()) / 2);
        JsonArray out = new JsonArray();
        for (int i = 0; i < n; i++) {
            for (int j = 0; j < n; j++) {
                double u = ((j + 0.5) / n) * 2 - 1, v = ((i + 0.5) / n) * 2 - 1;
                Vec3 dir = f.add(right.scale(u * t)).add(up.scale(-v * t)).normalize();
                Vec3 end = eye.add(dir.scale(64));
                BlockHitResult bh = mc.level.clip(new ClipContext(eye, end, ClipContext.Block.OUTLINE, ClipContext.Fluid.ANY, p));
                double bd = bh.getType() == HitResult.Type.BLOCK ? bh.getLocation().distanceTo(eye) : 64;
                Vec3 stop = eye.add(dir.scale(bd));
                var eh = net.minecraft.world.entity.projectile.ProjectileUtil.getEntityHitResult(p, eye, stop,
                    p.getBoundingBox().expandTowards(dir.scale(bd)).inflate(1), e -> e != p && !e.isSpectator(), bd * bd);
                JsonArray a = new JsonArray();
                if (eh != null) {
                    Entity e = eh.getEntity();
                    boolean item = e instanceof net.minecraft.world.entity.item.ItemEntity;
                    a.add(item ? "item" : e instanceof Player ? "player" : BuiltInRegistries.ENTITY_TYPE.getKey(e.getType()).getPath());
                    a.add(Math.round(eh.getLocation().distanceTo(eye) * 10) / 10.0);
                    a.add(item ? "item" : "mob");
                } else if (bh.getType() == HitResult.Type.BLOCK) {
                    a.add(name(mc.level.getBlockState(bh.getBlockPos())));
                    a.add(Math.round(bd * 10) / 10.0);
                    a.add("block");
                } else {
                    a.add(dir.y > -0.05 ? "sky" : "far");
                    a.add(64);
                    a.add("sky");
                }
                out.add(a);
            }
        }
        return out;
    }

    /** After a fine turn of the head: the nearest cardinal direction and the coarse pitch follow it. */
    static void syncHead(LocalPlayer p) {
        float yaw = p.getYRot();
        int best = 0;
        double bd = 999;
        for (int k = 0; k < 4; k++) {
            double d = Math.abs(((yaw - YAW[k]) % 360 + 540) % 360 - 180);
            if (d < bd) { bd = d; best = k; }
        }
        heading = best;
        pitch = p.getXRot() < -15 ? -1 : p.getXRot() > 15 ? 1 : 0;
    }
}
