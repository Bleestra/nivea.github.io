package ai.synapse.minecraft;

import baritone.api.BaritoneAPI;
import baritone.api.IBaritone;
import baritone.api.pathing.goals.Goal;
import baritone.api.pathing.goals.GoalNear;
import baritone.api.pathing.goals.GoalXZ;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.protocol.game.ServerboundSelectTradePacket;
import net.minecraft.tags.BlockTags;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.MobCategory;
import net.minecraft.world.entity.decoration.ArmorStand;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.AbstractFurnaceMenu;
import net.minecraft.world.inventory.ChestMenu;
import net.minecraft.world.inventory.ClickType;
import net.minecraft.world.inventory.CraftingMenu;
import net.minecraft.world.inventory.MerchantMenu;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.trading.MerchantOffer;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.Vec3;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.List;
import java.util.Random;
import java.util.concurrent.CompletableFuture;
import java.util.regex.Pattern;

/**
 * The motor system: every player action as a motor function. The brain chooses the action (and, for
 * the motor programs, what they are aimed at); here is only HOW the hands and legs do it - never when
 * or why. The numbers are the same as in bot.js, so what the brain learned there carries over.
 */
final class Motor {
    static final String[] ACTIONS = {"forward", "turn_left", "turn_right", "dig_front", "wait",
        "craft_new", "eat", "back", "strafe_left", "strafe_right", "jump", "toggle_sprint", "toggle_sneak",
        "look_up", "look_down", "attack", "use_item", "dig_down", "equip_armor", "equip_weapon",
        "equip_tool", "place_block", "craft_gear", "smelt", "sleep", "drop_junk", "pillar_up", "dig_up",
        "fish", "interact", "store", "take", "place_chest", "trade", "read",
        "approach", "mine_target", "craft_target", "goto_place", "explore", "place_frame",
        // what a player's hands do (41..59): turn the head a little, walk where I look, the mouse buttons
        // on whatever is under the crosshair, the hotbar keys, swap hands, drop - with these a body can
        // bridge, pillar, use a bucket, throw a pearl or an eye, fight: everything a person does
        "look_left_fine", "look_right_fine", "look_up_fine", "look_down_fine", "walk", "hit", "use", "hold_use",
        "hotbar_1", "hotbar_2", "hotbar_3", "hotbar_4", "hotbar_5", "hotbar_6", "hotbar_7", "hotbar_8", "hotbar_9",
        "swap_hands", "drop_item"};

    private static final Pattern SMELTABLE = Pattern.compile("^raw_|_ore$|^sand$|^cobblestone$|^beef$|^porkchop$|^chicken$|^mutton$|^cod$|^salmon$|^potato$|_log$");
    private static final Pattern FUEL = Pattern.compile("^coal$|^charcoal$|_planks$|_log$|^stick$");
    private static final Pattern NOT_PLACEABLE = Pattern.compile("table|furnace|bed|chest");
    private static final Pattern NOT_PILLAR = Pattern.compile("table|furnace|bed|chest|sapling|torch|slab|stairs|wall|fence|door|trapdoor|sand|gravel|leaves|glass");
    private static final Pattern PET_FOOD = Pattern.compile("^(cod|salmon|bone|wheat|carrot|seeds|wheat_seeds)$");
    private static final Random RNG = new Random();

    enum S { NEXT, WAIT, END }

    interface Step { S run(Minecraft mc); }

    /** A motor program: steps run on game ticks; a step may WAIT (try again next tick) or END the program. */
    static final class Program {
        final Deque<Step> steps = new ArrayDeque<>();
        int ticks, limit = 160;                                // no action may hang the body (8 s, as bot.js)
        final CompletableFuture<Void> done = new CompletableFuture<>();
        int action;
        String why;                                            // why it could not be done, when the hands know
        String need;                                           // what was missing, as the mind says it (have:X, see:X)
        Snapshot before;
        int settle = -1;                                       // ticks left to feel the result (the server answers late)
        Program then(Step s) { steps.addLast(s); return this; }
        void now(Step s) { steps.addFirst(s); }
    }

    /**
     * Efference copy: what the body was like before an action, to feel afterwards whether it did anything -
     * moved me, changed what I carry or wear, broke or placed a block, hit someone, opened something.
     */
    record Snapshot(Vec3 pos, java.util.Map<String, Integer> inv, String worn, int slot, boolean sleeping, int deeds) {
        static Snapshot of(Minecraft mc) {
            LocalPlayer p = mc.player;
            java.util.Map<String, Integer> inv = new java.util.HashMap<>();
            for (ItemStack s : p.getInventory().items) if (!s.isEmpty()) inv.merge(Hands.key(s), s.getCount(), Integer::sum);
            StringBuilder worn = new StringBuilder();
            for (ItemStack s : p.getInventory().armor) worn.append(Hands.key(s)).append(',');
            for (ItemStack s : p.getInventory().offhand) worn.append(Hands.key(s)).append(',');
            return new Snapshot(p.position(), inv, worn.toString(), p.getInventory().selected, p.isSleeping(), Senses.deeds);
        }
    }

    /** Actions that always "work" (turning the head, a key toggle): nothing to feel about them. */
    private static final java.util.Set<String> ALWAYS = java.util.Set.of("wait", "turn_left", "turn_right", "toggle_sprint",
        "toggle_sneak", "look_up", "look_down", "look_left_fine", "look_right_fine", "look_up_fine", "look_down_fine");
    /** Actions whose point is to get somewhere: they worked if I moved. */
    private static final java.util.Set<String> MOVES = java.util.Set.of("forward", "back", "strafe_left", "strafe_right",
        "jump", "walk", "approach", "goto_place", "explore");

    /** What the last action did: {a, action, ok, why} - the brain feels it with the next moment. */
    static volatile JsonObject lastResult;

    private static Program current;
    private static JsonElement target;

    /** A step that could not be done: say why, end the program. */
    static S fail(String why) {
        if (current != null && current.why == null) current.why = why;
        return S.END;
    }

    /** ... and what was missing (the mind can look up how to get it). */
    static S fail(String why, String need) {
        if (current != null && current.why == null) { current.why = why; current.need = need; }
        return S.END;
    }

    private Motor() {}

    static boolean busy() { return current != null; }

    /** On the client thread: begin what the brain answered. The future completes when the body is done. */
    static CompletableFuture<Void> start(Minecraft mc, JsonObject reply) {
        if (reply.has("say")) {
            String say = reply.get("say").getAsString();
            SynapseBody.said = say.length() > 120 ? say.substring(0, 119) + "…" : say;
            if (mc.player != null) mc.player.connection.sendChat(say.length() > 250 ? say.substring(0, 250) : say);
        }
        if (reply.has("hud") && reply.get("hud").isJsonObject()) SynapseBody.hud = reply.getAsJsonObject("hud");
        target = reply.get("target");
        int a = reply.has("action") ? reply.get("action").getAsInt() : 4;
        SynapseBody.doing = a >= 0 && a < ACTIONS.length ? ACTIONS[a] + (target != null && !target.isJsonNull() ? " → " + target : "") : "?";
        Program p = new Program();
        p.action = a;
        current = p;
        try {
            p.before = Snapshot.of(mc);
            plan(mc, a, p);
        } catch (Throwable error) {
            p.steps.clear();
        }
        tick(mc);                                              // instantaneous actions finish right away
        return p.done;
    }

    static void tick(Minecraft mc) {
        Program p = current;
        applyToggles(mc);
        if (p == null) return;
        p.ticks++;
        int guard = 0;
        try {
            while (!p.steps.isEmpty() && guard++ < 16) {
                Step step = p.steps.pollFirst();                // taken off first: a step may push new ones in front
                S s = step.run(mc);
                if (s == S.WAIT) { p.steps.addFirst(step); break; }
                if (s == S.END) p.steps.clear();
            }
        } catch (Throwable error) {
            p.steps.clear();
        }
        if (p.steps.isEmpty() || p.ticks > p.limit) {
            // the world answers a little later than the hands move (a bed, a chest, a trade...): let it settle,
            // then feel what the action did
            if (p.settle < 0) {
                p.settle = 6;
                release(mc);
            } else if (--p.settle <= 0) {
                finish(mc);
            }
        }
    }

    static void stop(Minecraft mc) {
        if (current != null) finish(mc);
    }

    private static void finish(Minecraft mc) {
        Program p = current;
        current = null;
        release(mc);
        try {
            IBaritone b = BaritoneAPI.getProvider().getPrimaryBaritone();
            if (b.getPathingBehavior().isPathing() || b.getCustomGoalProcess().isActive()) b.getPathingBehavior().cancelEverything();
        } catch (Throwable ignored) {
        }
        if (mc.gameMode != null && mc.gameMode.isDestroying()) mc.gameMode.stopDestroyBlock();
        if (mc.player != null && mc.player.isUsingItem()) mc.gameMode.releaseUsingItem(mc.player);
        if (p != null && mc.player != null && p.before != null) lastResult = outcome(mc, p);
        if (p != null) p.done.complete(null);
    }

    /** Did it do anything? Compare the body after with the body before (efference copy). */
    private static JsonObject outcome(Minecraft mc, Program p) {
        String name = p.action >= 0 && p.action < ACTIONS.length ? ACTIONS[p.action] : "?";
        Snapshot b = p.before, a = Snapshot.of(mc);
        boolean ok;
        String why = p.why;
        if (ALWAYS.contains(name) || name.startsWith("hotbar_")) {
            ok = true;
        } else if (MOVES.contains(name)) {
            double moved = a.pos().distanceTo(b.pos());
            ok = moved >= 0.3 || (name.equals("jump") && Math.abs(a.pos().y - b.pos().y) > 0.1);
            if (!ok && why == null) why = "не сдвинулся с места";
        } else {
            ok = !a.inv().equals(b.inv()) || !a.worn().equals(b.worn()) || a.slot() != b.slot()
                || a.sleeping() != b.sleeping() || a.deeds() != b.deeds();
            if (!ok && why == null) why = "ничего не изменилось";
        }
        JsonObject r = new JsonObject();
        r.addProperty("a", p.action);
        r.addProperty("action", name);
        r.addProperty("ok", ok);
        r.addProperty("ticks", p.ticks);                         // how long it took: the effort
        if (!ok) r.addProperty("why", why);
        if (!ok && p.need != null) r.addProperty("need", p.need);   // (set by fail(), or by the action itself)
        return r;
    }

    private static void release(Minecraft mc) {
        var o = mc.options;
        for (KeyMapping k : new KeyMapping[]{o.keyUp, o.keyDown, o.keyLeft, o.keyRight, o.keyJump, o.keyAttack, o.keyUse}) k.setDown(false);
        applyToggles(mc);
    }

    private static void applyToggles(Minecraft mc) {           // Shift and sprint stay as the brain left them
        if (mc.options == null) return;
        mc.options.keyShift.setDown(Senses.sneak);
        mc.options.keySprint.setDown(Senses.sprint);
    }

    // ------------------------------------------------------------------ the repertoire
    private static void plan(Minecraft mc, int a, Program p) {
        LocalPlayer pl = mc.player;
        int[] f = Senses.DIRS[Senses.heading < 0 ? 0 : Senses.heading];
        var o = mc.options;
        switch (ACTIONS[a]) {
            case "forward" -> p.then(face()).then(hold(6, o.keyUp));   // steps: the game's auto-jump (jumping from a standstill kills the run-up)
            case "turn_left" -> { Senses.heading = (Senses.heading + 3) % 4; p.then(face()); }
            case "turn_right" -> { Senses.heading = (Senses.heading + 1) % 4; p.then(face()); }
            case "dig_front" -> p.then(dig(rel(pl, f[0], 1, f[1]))).then(dig(rel(pl, f[0], 0, f[1])));
            case "wait" -> { }
            case "craft_new" -> {                             // something new: which one, the brain chooses
                String t = targetName();
                if (t.equals("#none")) p.then(m -> fail("жалко тратить то, что нужно для дела"));
                else craft(p, t.isEmpty() ? Hands.newThings(mc) : List.of(t));
            }
            case "eat" -> eat(p);
            case "back" -> p.then(hold(5, o.keyDown));
            case "strafe_left" -> p.then(hold(5, o.keyLeft));
            case "strafe_right" -> p.then(hold(5, o.keyRight));
            case "jump" -> p.then(hold(3, o.keyJump));
            case "toggle_sprint" -> Senses.sprint = !Senses.sprint;
            case "toggle_sneak" -> Senses.sneak = !Senses.sneak;   // holding Shift
            case "look_up" -> { Senses.pitch = Math.max(-1, Senses.pitch - 1); p.then(face()); }
            case "look_down" -> { Senses.pitch = Math.min(1, Senses.pitch + 1); p.then(face()); }
            case "attack" -> fight(p);
            case "use_item" -> useItem(mc, p);
            case "dig_down" -> p.then(dig(rel(pl, 0, -1, 0)));
            case "equip_armor" -> p.then(Motor::equipArmor);
            case "equip_weapon" -> p.then(m -> {
                Hands.hold(m, Hands.find(m.player, s -> Pattern.compile("_(sword|axe)$").matcher(Hands.key(s)).find(),
                    s -> Hands.tier(Hands.key(s)) * 2 + (Hands.key(s).endsWith("_sword") ? 1 : 0)));
                return S.NEXT;
            });
            case "equip_tool" -> p.then(m -> {
                BlockPos b = rel(m.player, f[0], 1, f[1]);
                if (m.level.getBlockState(b).isAir()) b = rel(m.player, f[0], 0, f[1]);
                equipToolFor(m, m.level.getBlockState(b));
                return S.NEXT;
            });
            case "place_block" -> p.then(placeFront(s -> Hands.isBlock(s) && !NOT_PLACEABLE.matcher(Hands.key(s)).find()));
            case "craft_gear" -> craft(p, Hands.GEAR);
            case "smelt" -> smelt(p);
            case "sleep" -> p.then(m -> {
                BlockPos bed = Hands.near(m, n -> n.endsWith("_bed"), 4);
                if (bed != null) p.now(use(bed));
                else { p.need = "have:white_bed"; p.now(placeFront(s -> Hands.key(s).endsWith("_bed"))); }
                return S.NEXT;
            });
            case "drop_junk" -> {                              // throw away a stack of the thing the brain chose
                String t = targetName();
                p.then(m -> {
                    if (t.isEmpty()) return fail("не выбрал, что выбросить");
                    int i = Hands.find(m.player, s -> Hands.key(s).equals(t), ItemStack::getCount);
                    if (i < 0) return fail("у меня нет " + t);
                    int slot = Hands.menuSlot(m.player, m.player.inventoryMenu, i);
                    if (slot >= 0 && m.player.containerMenu == m.player.inventoryMenu) Hands.click(m, slot, 1, ClickType.THROW);
                    return S.NEXT;
                });
            }
            case "pillar_up" -> pillarUp(p);
            case "dig_up" -> p.then(dig(rel(pl, 0, 2, 0)));
            case "fish" -> fish(p);
            case "interact" -> interact(p);
            case "store", "take" -> chest(p, ACTIONS[a].equals("store"));
            case "place_chest" -> { p.need = "have:chest"; p.then(placeFront(s -> Hands.key(s).equals("chest"))); }
            case "trade" -> trade(p);
            case "read" -> p.then(Motor::read);
            case "approach" -> p.then(m -> {
                String t = targetName();
                Entity e = Senses.nearestEntity(m, 16, x -> BuiltInRegistries.ENTITY_TYPE.getKey(x.getType()).getPath().equals(t));
                if (e != null) p.now(path(new GoalNear(e.blockPosition(), 2)));
                else {
                    BlockPos b = Senses.nearestSeenBlock(m, t);
                    if (b == null) return fail("не вижу " + t, "see:" + t);
                    p.now(path(new GoalNear(b, 1)));
                }
                return S.NEXT;
            });
            case "mine_target" -> p.then(m -> {
                BlockPos b = Senses.nearestSeenBlock(m, targetName());
                if (b == null) return fail("не вижу " + targetName(), "see:" + targetName());
                p.then(mm -> {                                  // then pick up what fell out, as a person walks over it
                    if (mm.level.getBlockState(b).isAir() && Vec3.atCenterOf(b).distanceTo(mm.player.position()) > 1.5) {
                        p.now(path(new GoalNear(b, 0)));
                    }
                    return S.NEXT;
                });
                p.now(dig(b));
                p.now(mm -> { equipToolFor(mm, mm.level.getBlockState(b)); return S.NEXT; });
                if (Vec3.atCenterOf(b).distanceTo(m.player.position()) > 4) p.now(path(new GoalNear(b, 2)));
                return S.NEXT;
            });
            case "craft_target" -> { p.need = targetName().isEmpty() ? null : "have:" + targetName(); craft(p, List.of(targetName())); }
            case "goto_place" -> {
                if (target != null && target.isJsonArray() && target.getAsJsonArray().size() >= 2) {
                    JsonArray t = target.getAsJsonArray();
                    p.then(t.size() >= 3 ? path(new GoalNear(new BlockPos(t.get(0).getAsInt(), t.get(1).getAsInt(), t.get(2).getAsInt()), 2))
                        : path(new GoalXZ(t.get(0).getAsInt(), t.get(1).getAsInt())));
                }
            }
            case "explore" -> {
                double ang = RNG.nextDouble() * 2 * Math.PI;
                p.then(path(new GoalXZ((int) Math.floor(pl.getX() + 24 * Math.cos(ang)), (int) Math.floor(pl.getZ() + 24 * Math.sin(ang)))));
            }
            case "place_frame" -> placeFrame(mc, p);
            case "look_left_fine" -> p.then(turn(-15F, 0F));
            case "look_right_fine" -> p.then(turn(15F, 0F));
            case "look_up_fine" -> p.then(turn(0F, -15F));
            case "look_down_fine" -> p.then(turn(0F, 15F));
            case "walk" -> p.then(hold(6, o.keyUp));                       // where I look (auto-jump on steps)
            case "hit" -> p.then(Motor::hitCrosshair);
            case "use" -> p.then(Motor::useCrosshair);
            case "hold_use" -> p.then(hold(40, o.keyUse));                 // eat, drink (32 ticks), draw a bow, raise a shield
            case "swap_hands" -> p.then(m -> {
                m.getConnection().send(new net.minecraft.network.protocol.game.ServerboundPlayerActionPacket(
                    net.minecraft.network.protocol.game.ServerboundPlayerActionPacket.Action.SWAP_ITEM_WITH_OFFHAND, BlockPos.ZERO, Direction.DOWN));
                return S.NEXT;
            });
            case "drop_item" -> p.then(m -> { m.player.drop(false); m.player.swing(InteractionHand.MAIN_HAND); return S.NEXT; });
            default -> {
                if (ACTIONS[a].startsWith("hotbar_")) {
                    int k = ACTIONS[a].charAt(7) - '1';
                    p.then(m -> { m.player.getInventory().setSelectedHotbarSlot(k); return S.NEXT; });
                }
            }
        }
    }

    /** Turn the head a little (as a mouse does): the coarse heading and pitch follow. */
    private static Step turn(float dyaw, float dpitch) {
        return m -> {
            m.player.setYRot(m.player.getYRot() + dyaw);
            m.player.setXRot(Math.max(-90F, Math.min(90F, m.player.getXRot() + dpitch)));
            m.player.yHeadRot = m.player.getYRot();
            Senses.syncHead(m.player);
            return S.NEXT;
        };
    }

    /** The left mouse button on what is under the crosshair: hit a being, or dig the block until it breaks. */
    private static S hitCrosshair(Minecraft m) {
        var hr = m.hitResult;
        if (hr instanceof net.minecraft.world.phys.EntityHitResult eh && hr.getType() == net.minecraft.world.phys.HitResult.Type.ENTITY) {
            Senses.lastHit = eh.getEntity().getId();
            Senses.deeds++;
            m.gameMode.attack(m.player, eh.getEntity());
            m.player.swing(InteractionHand.MAIN_HAND);
            return S.NEXT;
        }
        if (hr instanceof BlockHitResult bh && hr.getType() == net.minecraft.world.phys.HitResult.Type.BLOCK) {
            current.now(dig(bh.getBlockPos()));               // hold the button until the block breaks
            return S.NEXT;
        }
        m.player.swing(InteractionHand.MAIN_HAND);
        return fail("перед глазами пусто");
    }

    /** The right mouse button, as the game does it: on a being, on a block, else the item itself (bucket, pearl...). */
    private static S useCrosshair(Minecraft m) {
        var hr = m.hitResult;
        String held = Hands.key(m.player.getMainHandItem());
        boolean blockInHand = Hands.isBlock(m.player.getMainHandItem());
        if (hr instanceof net.minecraft.world.phys.EntityHitResult eh && hr.getType() == net.minecraft.world.phys.HitResult.Type.ENTITY) {
            if (m.gameMode.interact(m.player, eh.getEntity(), InteractionHand.MAIN_HAND).consumesAction()) {
                m.player.swing(InteractionHand.MAIN_HAND);
                Senses.deeds++;
                return S.NEXT;
            }
        } else if (hr instanceof BlockHitResult bh && hr.getType() == net.minecraft.world.phys.HitResult.Type.BLOCK) {
            BlockPos placedAt = bh.getBlockPos().relative(bh.getDirection());
            var r = m.gameMode.useItemOn(m.player, InteractionHand.MAIN_HAND, bh);
            if (r.consumesAction()) {
                m.player.swing(InteractionHand.MAIN_HAND);
                Senses.deeds++;
                if (blockInHand && Senses.name(m.level.getBlockState(placedAt)).equals(held)) Senses.placed(placedAt, held);
                return S.NEXT;
            }
        }
        if (m.gameMode.useItem(m.player, InteractionHand.MAIN_HAND).consumesAction()) Senses.deeds++;
        return S.NEXT;
    }

    private static String targetName() {
        return target == null || target.isJsonNull() ? "" : target.isJsonPrimitive() ? target.getAsString() : target.toString();
    }

    // ------------------------------------------------------------------ small motor pieces
    static BlockPos rel(LocalPlayer p, int dx, int dy, int dz) { return p.blockPosition().offset(dx, dy, dz); }

    /** Turn the head to the heading and pitch the brain keeps (as bot.js face()). */
    private static Step face() {
        return m -> {
            m.player.setYRot(Senses.YAW[Senses.heading < 0 ? 0 : Senses.heading]);
            m.player.setXRot(Senses.pitch * 33.7F);
            m.player.yHeadRot = m.player.getYRot();
            return S.NEXT;
        };
    }

    static void lookAt(Minecraft mc, Vec3 point) {
        LocalPlayer p = mc.player;
        double dx = point.x - p.getX(), dy = point.y - p.getEyeY(), dz = point.z - p.getZ();
        double h = Math.max(1e-6, Math.sqrt(dx * dx + dz * dz));
        p.setYRot((float) Math.toDegrees(Math.atan2(-dx, dz)));
        p.setXRot((float) Math.max(-90, Math.min(90, -Math.toDegrees(Math.atan2(dy, h)))));
        p.yHeadRot = p.getYRot();
    }

    private static Step hold(int ticks, KeyMapping... keys) {
        int[] left = {ticks};
        return m -> {
            if (left[0]-- <= 0) {
                for (KeyMapping k : keys) k.setDown(false);
                return S.NEXT;
            }
            for (KeyMapping k : keys) k.setDown(true);
            return S.WAIT;
        };
    }

    private static Step waitTicks(int n) {
        int[] left = {n};
        return m -> left[0]-- <= 0 ? S.NEXT : S.WAIT;
    }

    private static Direction faceToward(Vec3 eyeMinusCenter) {
        double ax = Math.abs(eyeMinusCenter.x), ay = Math.abs(eyeMinusCenter.y), az = Math.abs(eyeMinusCenter.z);
        if (ay >= ax && ay >= az) return eyeMinusCenter.y > 0 ? Direction.UP : Direction.DOWN;
        if (ax >= az) return eyeMinusCenter.x > 0 ? Direction.EAST : Direction.WEST;
        return eyeMinusCenter.z > 0 ? Direction.SOUTH : Direction.NORTH;
    }

    /** Longest a hand keeps the button down on one block (30 s). Obsidian by hand (250 s) is not worth it. */
    private static final int MAX_DIG_TICKS = 600;

    /**
     * Dig one block with whatever is in the hand, holding the button until it breaks - as long as it takes
     * with this hand and this tool (the game says how much of the block one tick breaks: stone by hand
     * 7.5 s, with a wooden pickaxe 1.1 s). The action is not cut short while the block is still breaking.
     */
    private static Step dig(BlockPos pos) {
        int[] t = {0};
        int[] need = {0};
        Direction[] side = {null};
        String[] what = {null};
        return m -> {
            BlockState s = m.level.getBlockState(pos);
            if (s.isAir() || !s.getFluidState().isEmpty() && s.getCollisionShape(m.level, pos).isEmpty()) {
                if (t[0] > 0) {
                    Senses.dug(pos);
                    if (what[0] != null) Senses.broke(m, what[0]);   // what did breaking it give me? (felt a moment later)
                }
                return S.NEXT;
            }
            if (t[0] == 0) what[0] = Senses.name(s);
            if (s.getDestroySpeed(m.level, pos) < 0) return S.NEXT;                     // bedrock and the like
            if (m.player.getEyePosition().distanceTo(Vec3.atCenterOf(pos)) > 5.0) return S.NEXT;
            Vec3 c = Vec3.atCenterOf(pos);
            lookAt(m, c);
            if (t[0]++ == 0) {
                float perTick = s.getDestroyProgress(m.player, m.level, pos);
                need[0] = perTick <= 0 ? Integer.MAX_VALUE : (int) Math.ceil(1.0 / perTick);
                if (need[0] > MAX_DIG_TICKS) return S.NEXT;                            // with this hand: hopeless
                if (current != null) current.limit = Math.max(current.limit, current.ticks + need[0] + 40);
                side[0] = faceToward(m.player.getEyePosition().subtract(c));
                m.gameMode.startDestroyBlock(pos, side[0]);
            } else {
                m.gameMode.continueDestroyBlock(pos, side[0]);
            }
            m.player.swing(InteractionHand.MAIN_HAND);
            if (t[0] > need[0] + 30) { m.gameMode.stopDestroyBlock(); return S.NEXT; }   // something keeps it whole
            return S.WAIT;
        };
    }

    /** Right-click a block (open it, sleep in it, use the held item on it). */
    private static Step use(BlockPos pos) {
        return m -> {
            Vec3 c = Vec3.atCenterOf(pos);
            if (m.player.getEyePosition().distanceTo(c) > 5.0) return S.NEXT;
            Direction side = faceToward(m.player.getEyePosition().subtract(c));
            Vec3 hit = c.add(side.getStepX() * 0.5, side.getStepY() * 0.5, side.getStepZ() * 0.5);
            lookAt(m, hit);
            boolean shift = Senses.sneak;
            m.options.keyShift.setDown(false);
            m.gameMode.useItemOn(m.player, InteractionHand.MAIN_HAND, new BlockHitResult(hit, side, pos, false));
            m.player.swing(InteractionHand.MAIN_HAND);
            m.options.keyShift.setDown(shift);
            return S.NEXT;
        };
    }

    /** Put a block from the inventory on the ground: in front, else any side (as bot.js placeFront). */
    private static Step placeFront(java.util.function.Predicate<ItemStack> which) {
        return m -> {
            LocalPlayer p = m.player;
            int inv = Hands.find(p, which);
            if (inv < 0) return fail("нечего поставить");
            BlockPos base = p.blockPosition();
            java.util.List<int[]> spots = new java.util.ArrayList<>();
            for (int k = 0; k < 4; k++) spots.add(Senses.DIRS[(Math.max(0, Senses.heading) + k) % 4]);
            for (int dx = -2; dx <= 2; dx++) for (int dz = -2; dz <= 2; dz++) if (Math.abs(dx) + Math.abs(dz) >= 2) spots.add(new int[]{dx, dz});
            for (int[] s : spots) {
                BlockPos ground = base.offset(s[0], -1, s[1]), spot = base.offset(s[0], 0, s[1]);
                if (!Senses.solid(m, ground) || !m.level.getBlockState(spot).getCollisionShape(m.level, spot).isEmpty()) continue;
                if (!m.level.getBlockState(spot).canBeReplaced()) continue;
                String name = Hands.key(p.getInventory().items.get(inv));
                if (!Hands.hold(m, inv)) return fail("не могу взять в руку");
                Vec3 hit = Vec3.atCenterOf(ground).add(0, 0.5, 0);
                lookAt(m, hit);
                var r = m.gameMode.useItemOn(p, InteractionHand.MAIN_HAND, new BlockHitResult(hit, Direction.UP, ground, false));
                p.swing(InteractionHand.MAIN_HAND);
                if (r.consumesAction()) Senses.placed(spot, name);
                return S.NEXT;
            }
            return fail("некуда поставить");
        };
    }

    /** Walk there along a path (Baritone): a motor program, like mineflayer-pathfinder in bot.js. */
    private static Step path(Goal goal) {
        int[] t = {0};
        return m -> {
            IBaritone b = BaritoneAPI.getProvider().getPrimaryBaritone();
            if (t[0]++ == 0) {
                b.getCustomGoalProcess().setGoalAndPath(goal);
                return S.WAIT;
            }
            if (t[0] > 3 && !b.getCustomGoalProcess().isActive() && !b.getPathingBehavior().isPathing()) return S.NEXT;
            return S.WAIT;
        };
    }

    private static Step openedWait(Class<? extends AbstractContainerMenu> kind) {
        int[] t = {0};
        return m -> {
            if (kind.isInstance(m.player.containerMenu)) { Senses.deeds++; return S.NEXT; }   // it opened
            return t[0]++ > 30 ? fail("не открылось") : S.WAIT;
        };
    }

    private static Step close() {
        return m -> {
            if (m.player.containerMenu != m.player.inventoryMenu) m.player.closeContainer();
            return S.NEXT;
        };
    }

    private static void equipToolFor(Minecraft mc, BlockState s) {
        String kind = s.is(BlockTags.MINEABLE_WITH_PICKAXE) ? "_pickaxe" : s.is(BlockTags.MINEABLE_WITH_AXE) ? "_axe"
            : s.is(BlockTags.MINEABLE_WITH_SHOVEL) ? "_shovel" : null;
        if (kind == null) return;
        Hands.hold(mc, Hands.find(mc.player, x -> Hands.key(x).endsWith(kind), x -> Hands.tier(Hands.key(x))));
    }

    // ------------------------------------------------------------------ the bigger motor programs
    /**
     * Fight: go at the one the brain chose, keep facing it and strike whenever the arm is ready again (the attack
     * cooldown: a half-charged blow barely hurts), until it falls or gets away - at most 5 s, then the brain
     * decides again whether to go on. Whom to fight is the brain's choice (an entity id, a kind or a mob's name);
     * with none, the nearest creature within reach.
     */
    private static void fight(Program p) {
        JsonElement tg = target;
        int[] foe = {-1};
        p.limit = 100;
        p.then(m -> {
            Entity t = foe(m, tg);
            if (t == null) { m.player.swing(InteractionHand.MAIN_HAND); return fail("не по кому бить"); }
            foe[0] = t.getId();
            return S.NEXT;
        });
        p.then(m -> {
            Entity t = m.level.getEntity(foe[0]);
            if (t == null || !t.isAlive() || t.distanceTo(m.player) > 16) return S.END;   // it fell, or got away
            lookAt(m, t.position().add(0, t.getBbHeight() * 0.8, 0));
            double d = t.distanceTo(m.player);
            m.options.keyUp.setDown(d > 2.5);                                            // close in
            if (d <= 3.0 && m.player.getAttackStrengthScale(0.5F) >= 0.95F) {
                Senses.lastHit = t.getId();
                Senses.deeds++;
                m.gameMode.attack(m.player, t);
                m.player.swing(InteractionHand.MAIN_HAND);
            }
            return S.WAIT;
        });
    }

    private static Entity foe(Minecraft m, JsonElement tg) {
        java.util.function.Predicate<Entity> living = e -> e instanceof LivingEntity && e.isAlive() && e != m.player
            && !(e instanceof ArmorStand);
        if (tg != null && tg.isJsonPrimitive() && tg.getAsJsonPrimitive().isNumber()) {
            Entity e = m.level.getEntity(tg.getAsInt());
            return e != null && living.test(e) && e.distanceTo(m.player) <= 16 ? e : null;
        }
        String k = tg != null && tg.isJsonPrimitive() ? tg.getAsString() : "";
        if (k.isEmpty()) return Senses.nearestEntity(m, 4.5, e -> living.test(e) && !(e instanceof Player));
        return Senses.nearestEntity(m, 16, e -> living.test(e) && (k.equals(Senses.kindOf(e))
            || k.equals(BuiltInRegistries.ENTITY_TYPE.getKey(e.getType()).getPath())));
    }

    private static void eat(Program p) {
        int[] before = {-1};
        String[] what = {null};
        p.then(m -> {
            List<Integer> foods = new java.util.ArrayList<>();
            var items = m.player.getInventory().items;
            for (int i = 0; i < items.size(); i++) if (!items.get(i).isEmpty() && Hands.isFood(items.get(i))) foods.add(i);
            if (foods.isEmpty()) return fail("нечего есть", "have:bread");
            if (m.player.getFoodData().getFoodLevel() >= 20) return fail("не голоден");
            int i = foods.get(RNG.nextInt(foods.size()));
            what[0] = Hands.key(items.get(i));
            before[0] = Hands.count(m.player, what[0]);
            return Hands.hold(m, i) ? S.NEXT : S.END;
        });
        int[] t = {0};
        p.then(m -> {
            if (Hands.count(m.player, what[0]) < before[0]) {
                m.options.keyUse.setDown(false);
                Senses.ate = what[0];
                Senses.deeds++;
                return S.NEXT;
            }
            m.options.keyUse.setDown(true);
            return t[0]++ > 45 ? S.NEXT : S.WAIT;
        });
        p.limit = 80;
    }

    private static void useItem(Minecraft mc, Program p) {
        LocalPlayer pl = mc.player;
        int flint = Hands.findNamed(pl, Pattern.compile("^flint_and_steel$"));
        BlockPos obsidian = flint >= 0 ? lowest(mc, "obsidian", 6) : null;
        if (obsidian != null) {                                // light the portal: strike the lowest obsidian's top
            p.then(m -> Hands.hold(m, flint) ? S.NEXT : S.END).then(useFace(obsidian, Direction.UP));
            return;
        }
        int eye = Hands.findNamed(pl, Pattern.compile("^ender_eye$"));
        if (eye >= 0) {
            BlockPos frame = Hands.near(mc, n -> n.equals("end_portal_frame"), 5);
            if (frame != null && !mc.level.getBlockState(frame).toString().contains("eye=true")) {
                p.then(m -> Hands.hold(m, eye) ? S.NEXT : S.END).then(useFace(frame, Direction.UP));
                return;
            }
            p.then(m -> {
                if (!Hands.hold(m, eye)) return S.END;
                m.player.setXRot(-17F);
                m.gameMode.useItem(m.player, InteractionHand.MAIN_HAND);
                return S.NEXT;
            }).then(waitTicks(20));
            return;
        }
        int bow = Hands.findNamed(pl, Pattern.compile("^bow$"));
        Entity foe = bow >= 0 && Hands.count(pl, "arrow") > 0 ? Senses.nearestEntity(mc, 24, e ->
            e.getType().getCategory() == MobCategory.MONSTER || e.getType().toString().contains("end_crystal")
                || e.getType().toString().contains("ender_dragon")) : null;
        if (foe != null) {
            int[] t = {0};
            p.then(m -> Hands.hold(m, bow) ? S.NEXT : S.END).then(m -> {
                lookAt(m, foe.position().add(0, foe.getBbHeight() * 0.7, 0));
                m.options.keyUse.setDown(t[0]++ < 22);
                return t[0] > 22 ? S.NEXT : S.WAIT;
            });
            return;
        }
        p.then(hold(10, mc.options.keyUse));
    }

    private static Step useFace(BlockPos pos, Direction side) {
        return m -> {
            Vec3 hit = Vec3.atCenterOf(pos).add(side.getStepX() * 0.5, side.getStepY() * 0.5, side.getStepZ() * 0.5);
            lookAt(m, hit);
            m.gameMode.useItemOn(m.player, InteractionHand.MAIN_HAND, new BlockHitResult(hit, side, pos, false));
            m.player.swing(InteractionHand.MAIN_HAND);
            return S.NEXT;
        };
    }

    private static BlockPos lowest(Minecraft mc, String name, int r) {
        BlockPos p = mc.player.blockPosition(), best = null;
        for (BlockPos q : BlockPos.betweenClosed(p.offset(-r, -r, -r), p.offset(r, r, r))) {
            if (q.distSqr(p) <= r * r && Senses.name(mc.level.getBlockState(q)).equals(name) && (best == null || q.getY() < best.getY())) best = q.immutable();
        }
        return best;
    }

    private static S equipArmor(Minecraft m) {
        LocalPlayer p = m.player;
        if (p.containerMenu != p.inventoryMenu) return S.NEXT;
        var slots = new net.minecraft.world.entity.EquipmentSlot[]{net.minecraft.world.entity.EquipmentSlot.HEAD,
            net.minecraft.world.entity.EquipmentSlot.CHEST, net.minecraft.world.entity.EquipmentSlot.LEGS,
            net.minecraft.world.entity.EquipmentSlot.FEET};
        int[] armorMenuSlot = {5, 6, 7, 8};                    // InventoryMenu: head, chest, legs, feet
        for (int k = 0; k < 4; k++) {
            var slot = slots[k];
            int best = Hands.find(p, s -> {
                var eq = s.get(DataComponents.EQUIPPABLE);
                return eq != null && eq.slot() == slot && Hands.armorRank(Hands.key(s)) > 0;
            }, s -> Hands.armorRank(Hands.key(s)));
            if (best < 0) continue;
            ItemStack worn = p.getItemBySlot(slot);
            if (!worn.isEmpty() && Hands.armorRank(Hands.key(worn)) >= Hands.armorRank(Hands.key(p.getInventory().items.get(best)))) continue;
            int from = Hands.menuSlot(p, p.inventoryMenu, best);
            if (worn.isEmpty()) {
                Hands.click(m, from, 0, ClickType.QUICK_MOVE);
            } else {                                           // swap: pick the better one, put it on, put the old one back
                Hands.click(m, from, 0, ClickType.PICKUP);
                Hands.click(m, armorMenuSlot[k], 0, ClickType.PICKUP);
                Hands.click(m, from, 0, ClickType.PICKUP);
            }
        }
        return S.NEXT;
    }

    /** Craft through the recipe book: in the hands (2x2) or at a table (3x3), placing a table if I carry one. */
    private static void craft(Program p, List<String> wanted) {
        boolean[] triedTable = {false};
        p.then(new Step() {
            @Override
            public S run(Minecraft m) {
                List<Hands.Craft> can = Hands.craftable(m, wanted);
                if (can.isEmpty()) {
                    if (!triedTable[0] && Hands.tableNear(m) == null && Hands.count(m.player, "crafting_table") > 0) {
                        triedTable[0] = true;
                        p.now(this);
                        p.now(waitTicks(3));
                        p.now(placeFront(s -> Hands.key(s).equals("crafting_table")));
                        return S.NEXT;
                    }
                    return fail("не из чего смастерить");
                }
                Hands.Craft c = can.get(0);
                BlockPos table = Hands.tableNear(m);
                if (c.small() && table == null) {              // in my own hands: the inventory's 2x2 grid
                    p.now(returnGrid(1, 4));
                    p.now(waitTicks(1));
                    p.now(takeResult(c.name()));
                    p.now(waitTicks(2));
                    p.now(mm -> { mm.gameMode.handlePlaceRecipe(mm.player.inventoryMenu.containerId, c.id(), false); return S.NEXT; });
                } else {
                    p.now(close());
                    p.now(waitTicks(1));
                    p.now(takeResult(c.name()));
                    p.now(waitTicks(2));
                    p.now(mm -> { mm.gameMode.handlePlaceRecipe(mm.player.containerMenu.containerId, c.id(), false); return S.NEXT; });
                    p.now(openedWait(CraftingMenu.class));
                    p.now(use(table));
                }
                return S.NEXT;
            }
        });
        p.limit = 200;
    }

    private static Step takeResult(String name) {
        return m -> {
            Slot out = m.player.containerMenu.getSlot(0);
            if (out.hasItem()) Hands.click(m, 0, 0, ClickType.QUICK_MOVE);
            return S.NEXT;
        };
    }

    private static Step returnGrid(int from, int to) {
        return m -> {
            for (int s = from; s <= to; s++) if (m.player.containerMenu.getSlot(s).hasItem()) Hands.click(m, s, 0, ClickType.QUICK_MOVE);
            return S.NEXT;
        };
    }

    private static void smelt(Program p) {
        p.then(new Step() {
            boolean placed;

            @Override
            public S run(Minecraft m) {
                BlockPos fur = Hands.near(m, n -> n.equals("furnace"), 4);
                if (fur == null) {
                    if (placed || Hands.count(m.player, "furnace") == 0) return fail("рядом нет печи", "have:furnace");
                    placed = true;
                    p.now(this);
                    p.now(waitTicks(3));
                    p.now(placeFront(s -> Hands.key(s).equals("furnace")));
                    return S.NEXT;
                }
                p.now(close());
                p.now(waitTicks(2));
                p.now(mm -> {
                    AbstractContainerMenu menu = mm.player.containerMenu;
                    if (menu.getSlot(2).hasItem()) Hands.click(mm, 2, 0, ClickType.QUICK_MOVE);    // what is ready
                    int in = Hands.find(mm.player, s -> SMELTABLE.matcher(Hands.key(s)).find());
                    String inName = in < 0 ? "" : Hands.key(mm.player.getInventory().items.get(in));
                    int fuel = Hands.find(mm.player, s -> FUEL.matcher(Hands.key(s)).find() && !Hands.key(s).equals(inName));
                    if (fuel >= 0 && !menu.getSlot(1).hasItem()) put(mm, menu, fuel, 1);
                    in = Hands.find(mm.player, s -> Hands.key(s).equals(inName));
                    if (in >= 0 && !menu.getSlot(0).hasItem()) put(mm, menu, in, 0);
                    return S.NEXT;
                });
                p.now(openedWait(AbstractFurnaceMenu.class));
                p.now(use(fur));
                return S.NEXT;
            }
        });
        p.limit = 120;
    }

    /** Carry a whole stack from the inventory into a slot of the open menu (what does not fit goes back). */
    private static void put(Minecraft m, AbstractContainerMenu menu, int inv, int slot) {
        int from = Hands.menuSlot(m.player, menu, inv);
        if (from < 0) return;
        Hands.click(m, from, 0, ClickType.PICKUP);
        Hands.click(m, slot, 0, ClickType.PICKUP);
        if (!menu.getCarried().isEmpty()) Hands.click(m, from, 0, ClickType.PICKUP);
    }

    private static void pillarUp(Program p) {
        double[] y0 = {0};
        int[] t = {0};
        BlockPos[] below = {null};
        p.then(m -> {
            int blk = Hands.find(m.player, s -> Hands.isBlock(s) && !NOT_PILLAR.matcher(Hands.key(s)).find(), ItemStack::getCount);
            below[0] = m.player.blockPosition().below();
            if (blk < 0) return fail("нет блоков", "have:dirt");
            if (!Senses.solid(m, below[0]) || !Hands.hold(m, blk)) return fail("не на что встать");
            m.player.setXRot(90F);
            y0[0] = m.player.getY();
            return S.NEXT;
        }).then(m -> {
            m.options.keyJump.setDown(true);
            return m.player.getY() >= y0[0] + 1.0 || t[0]++ > 10 ? S.NEXT : S.WAIT;
        }).then(m -> {
            m.options.keyJump.setDown(false);
            String name = Hands.key(m.player.getMainHandItem());
            Vec3 hit = Vec3.atCenterOf(below[0]).add(0, 0.5, 0);
            var r = m.gameMode.useItemOn(m.player, InteractionHand.MAIN_HAND, new BlockHitResult(hit, Direction.UP, below[0], false));
            m.player.swing(InteractionHand.MAIN_HAND);
            if (r.consumesAction()) Senses.placed(below[0].above(), name);
            return S.NEXT;
        }).then(face());
    }

    private static void fish(Program p) {
        int[] t = {0};
        p.then(m -> {
            int rod = Hands.findNamed(m.player, Pattern.compile("^fishing_rod$"));
            if (rod < 0 || !Hands.hold(m, rod)) return fail("нет удочки", "have:fishing_rod");
            m.gameMode.useItem(m.player, InteractionHand.MAIN_HAND);         // cast
            return S.NEXT;
        }).then(m -> {
            var hook = m.player.fishing;
            t[0]++;
            if (hook == null) return t[0] > 20 ? fail("поплавок не упал в воду") : S.WAIT;
            if (t[0] == 1 || t[0] == 21) Senses.deeds++;                   // the line is out
            if (((ai.synapse.minecraft.mixin.FishingHookAccessor) hook).synapse$isBiting() || t[0] > 400) {
                m.gameMode.useItem(m.player, InteractionHand.MAIN_HAND);     // the line tugs: pull
                return S.NEXT;
            }
            return S.WAIT;
        }).then(waitTicks(10));
        p.limit = 440;
    }

    private static boolean villager(Entity e) {
        String n = BuiltInRegistries.ENTITY_TYPE.getKey(e.getType()).getPath();
        return n.equals("villager") || n.equals("wandering_trader");
    }

    /** Right-click the nearest being: feed, tame, greet - or open a villager's trades and look at them. */
    private static void interact(Program p) {
        p.then(m -> {
            Entity t = Senses.nearestEntity(m, 4, e -> villager(e) || e instanceof Player
                || e.getType().getCategory() == MobCategory.CREATURE
                || Pattern.compile("cat|ocelot|wolf|parrot").matcher(BuiltInRegistries.ENTITY_TYPE.getKey(e.getType()).getPath()).find());
            if (t == null) return fail("рядом никого нет");
            if (villager(t)) {
                p.now(close());
                p.now(waitTicks(10));
                p.now(Motor::lookAtTrades);
                p.now(openedWait(MerchantMenu.class));
                p.now(mm -> { lookAt(mm, t.position().add(0, 1.5, 0)); mm.gameMode.interact(mm.player, t, InteractionHand.MAIN_HAND); return S.NEXT; });
                return S.NEXT;
            }
            int food = Hands.find(m.player, s -> PET_FOOD.matcher(Hands.key(s)).find());
            if (food < 0) food = Hands.find(m.player, Hands::isFood);
            if (food >= 0) Hands.hold(m, food);
            lookAt(m, t.position().add(0, t.getBbHeight() * 0.7, 0));
            if (m.gameMode.interact(m.player, t, InteractionHand.MAIN_HAND).consumesAction()) Senses.deeds++;
            m.player.swing(InteractionHand.MAIN_HAND);
            return S.NEXT;
        });
    }

    /** The trading window is open: the eyes read the offers (payment -> goods, and whether sold out). */
    private static S lookAtTrades(Minecraft m) {
        if (!(m.player.containerMenu instanceof MerchantMenu mm)) return S.NEXT;
        JsonArray list = new JsonArray();
        for (MerchantOffer o : mm.getOffers()) {
            JsonArray x = new JsonArray();
            String pay = o.getCostA().getCount() + "x" + Hands.key(o.getCostA());
            if (!o.getCostB().isEmpty()) pay += "+" + o.getCostB().getCount() + "x" + Hands.key(o.getCostB());
            x.add(pay);
            x.add(o.getResult().getCount() + "x" + Hands.key(o.getResult()));
            x.add(o.isOutOfStock());
            list.add(x);
        }
        Senses.trades = list;
        Senses.deeds++;
        return S.NEXT;
    }

    private static void trade(Program p) {
        p.then(m -> {
            Entity v = Senses.nearestEntity(m, 4, Motor::villager);
            if (v == null) return fail("рядом нет жителя", "see:villager");
            p.now(close());
            p.now(waitTicks(2));
            p.now(mm -> {                                      // the first offer I can pay for
                if (!(mm.player.containerMenu instanceof MerchantMenu menu)) return S.END;
                var offers = menu.getOffers();
                for (int k = 0; k < offers.size(); k++) {
                    MerchantOffer o = offers.get(k);
                    if (o.isOutOfStock()) continue;
                    if (Hands.count(mm.player, Hands.key(o.getCostA())) < o.getCostA().getCount()) continue;
                    if (!o.getCostB().isEmpty() && Hands.count(mm.player, Hands.key(o.getCostB())) < o.getCostB().getCount()) continue;
                    menu.setSelectionHint(k);
                    menu.tryMoveItems(k);
                    mm.getConnection().send(new ServerboundSelectTradePacket(k));
                    int kk = k;
                    p.now(x -> {
                        if (x.player.containerMenu.getSlot(2).hasItem()) {
                            Senses.traded = Hands.key(offers.get(kk).getResult());
                            Senses.deeds++;
                            Hands.click(x, 2, 0, ClickType.QUICK_MOVE);
                        }
                        return S.NEXT;
                    });
                    p.now(waitTicks(3));
                    return S.NEXT;
                }
                return S.NEXT;
            });
            p.now(Motor::lookAtTrades);
            p.now(openedWait(MerchantMenu.class));
            p.now(mm -> { lookAt(mm, v.position().add(0, 1.5, 0)); mm.gameMode.interact(mm.player, v, InteractionHand.MAIN_HAND); return S.NEXT; });
            return S.NEXT;
        });
    }

    /** Put the thing the brain chose into the chest in front, or take it out; then look at what is in there. */
    private static void chest(Program p, boolean store) {
        String t = targetName();
        p.then(m -> {
            if (t.isEmpty()) return fail(store ? "не выбрал, что положить" : "не выбрал, что взять");
            BlockPos c = Hands.near(m, n -> n.equals("chest"), 4);
            if (c == null) return fail("рядом нет сундука", "have:chest");
            if (store && Hands.find(m.player, s -> Hands.key(s).equals(t)) < 0) return fail("у меня нет " + t);
            p.now(close());
            p.now(mm -> { Senses.chest = contents(mm, c); return S.NEXT; });   // what is in it now: to remember
            p.now(waitTicks(3));
            p.now(mm -> {
                boolean moved = false;
                for (Slot s : mm.player.containerMenu.slots) {
                    if (!s.hasItem() || !Hands.key(s.getItem()).equals(t)) continue;
                    if ((s.container == mm.player.getInventory()) == store) { Hands.click(mm, s.index, 0, ClickType.QUICK_MOVE); moved = true; }
                }
                if (!moved && current != null && current.why == null) current.why = store ? "некуда положить" : "в сундуке нет " + t;
                return S.NEXT;
            });
            p.now(openedWait(ChestMenu.class));
            p.now(use(c));
            return S.NEXT;
        });
    }

    private static JsonObject contents(Minecraft mc, BlockPos c) {
        java.util.Map<String, Integer> in = new java.util.LinkedHashMap<>();
        for (Slot s : mc.player.containerMenu.slots)
            if (s.hasItem() && s.container != mc.player.getInventory()) in.merge(Hands.key(s.getItem()), s.getItem().getCount(), Integer::sum);
        JsonObject o = new JsonObject(), items = new JsonObject();
        JsonArray at = new JsonArray();
        at.add(c.getX());
        at.add(c.getY());
        at.add(c.getZ());
        in.forEach(items::addProperty);
        o.add("at", at);
        o.add("items", items);
        return o;
    }

    private static S read(Minecraft m) {
        for (ItemStack s : m.player.getInventory().items) {
            var written = s.get(DataComponents.WRITTEN_BOOK_CONTENT);
            if (written != null) {
                StringBuilder b = new StringBuilder();
                for (var page : written.getPages(false)) b.append(page.getString()).append(' ');
                Senses.read = b.toString().trim();
                Senses.deeds++;
                return S.NEXT;
            }
            var writable = s.get(DataComponents.WRITABLE_BOOK_CONTENT);
            if (writable != null) {
                Senses.read = String.join(" ", writable.getPages(false).toList()).trim();
                Senses.deeds++;
                return S.NEXT;
            }
        }
        return S.NEXT;
    }

    /** A nether portal frame: 10 obsidian in a 4x5 frame 2 blocks ahead; corners from any block. */
    private static void placeFrame(Minecraft mc, Program p) {
        if (Hands.count(mc.player, "obsidian") < 10) return;
        int h = Math.max(0, Senses.heading);
        int[] f = Senses.DIRS[h], r = Senses.DIRS[(h + 1) % 4];
        BlockPos base = mc.player.blockPosition();
        int[][] plan = {{1, 0, 1}, {2, 0, 1}, {0, 0, 0}, {3, 0, 0}, {0, 1, 1}, {3, 1, 1}, {0, 2, 1}, {3, 2, 1},
            {0, 3, 1}, {3, 3, 1}, {0, 4, 0}, {3, 4, 0}, {1, 4, 1}, {2, 4, 1}};
        for (int[] step : plan) {
            BlockPos pos = base.offset(f[0] * 2 + r[0] * (step[0] - 1), step[1], f[1] * 2 + r[1] * (step[0] - 1));
            boolean obsidian = step[2] == 1;
            p.then(m -> {
                if (!m.level.getBlockState(pos).getCollisionShape(m.level, pos).isEmpty()) return S.NEXT;
                int item = obsidian ? Hands.findNamed(m.player, Pattern.compile("^obsidian$"))
                    : Hands.find(m.player, s -> Hands.isBlock(s) && !Hands.key(s).equals("obsidian") && !NOT_PLACEABLE.matcher(Hands.key(s)).find());
                if (item < 0) return fail("не хватает блоков", "have:obsidian");
                String name = Hands.key(m.player.getInventory().items.get(item));
                for (Direction d : new Direction[]{Direction.DOWN, Direction.EAST, Direction.WEST, Direction.SOUTH, Direction.NORTH, Direction.UP}) {
                    BlockPos ref = pos.relative(d);
                    if (!Senses.solid(m, ref)) continue;
                    if (!Hands.hold(m, item)) return S.END;
                    Direction side = d.getOpposite();
                    Vec3 hit = Vec3.atCenterOf(ref).add(side.getStepX() * 0.5, side.getStepY() * 0.5, side.getStepZ() * 0.5);
                    lookAt(m, hit);
                    var res = m.gameMode.useItemOn(m.player, InteractionHand.MAIN_HAND, new BlockHitResult(hit, side, ref, false));
                    m.player.swing(InteractionHand.MAIN_HAND);
                    if (res.consumesAction()) Senses.placed(pos, name);
                    break;
                }
                return S.NEXT;
            }).then(waitTicks(2));
        }
        p.limit = 200;
    }
}
