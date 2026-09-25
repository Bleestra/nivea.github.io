package ai.synapse.minecraft;

import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.recipebook.RecipeCollection;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.player.StackedItemContents;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ClickType;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.display.RecipeDisplay;
import net.minecraft.world.item.crafting.display.RecipeDisplayEntry;
import net.minecraft.world.item.crafting.display.RecipeDisplayId;
import net.minecraft.world.item.crafting.display.ShapedCraftingRecipeDisplay;
import net.minecraft.world.item.crafting.display.ShapelessCraftingRecipeDisplay;
import net.minecraft.world.item.crafting.display.SlotDisplayContext;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Predicate;
import java.util.regex.Pattern;

/**
 * The hands: what is in the inventory, taking a thing into the hand, clicking slots, and the recipe book.
 * Crafting goes through the game's own recipe book, as a player does: only recipes the game has shown
 * the player can be made, and only when the ingredients are really there.
 */
final class Hands {
    static final String[] TIERS = {"wooden", "stone", "iron", "golden", "diamond", "netherite"};
    static final String[] ARMOR = {"leather", "golden", "chainmail", "iron", "diamond", "netherite"};
    static final Pattern GEAR_RE = Pattern.compile("_(pickaxe|sword|axe|shovel|helmet|chestplate|leggings|boots)$|^shield$");
    /** Marker: "anything with a gear name" (craft_gear). */
    static final List<String> GEAR = List.of("#gear");

    private Hands() {}

    static String key(ItemStack s) {
        return s.isEmpty() ? "" : BuiltInRegistries.ITEM.getKey(s.getItem()).getPath();
    }

    static int tier(String n) {
        for (int i = 0; i < TIERS.length; i++) if (n.startsWith(TIERS[i] + "_")) return i + 1;
        return 0;
    }

    static int armorRank(String n) {
        for (int i = 0; i < ARMOR.length; i++) if (n.startsWith(ARMOR[i] + "_")) return i + 1;
        return 0;
    }

    static int gearValue(String n) {
        return Math.max(tier(n), armorRank(n)) * 10 + (n.endsWith("_pickaxe") ? 3 : n.endsWith("_sword") ? 2 : 1);
    }

    static boolean isFood(ItemStack s) { return s.has(DataComponents.FOOD); }

    static boolean isBlock(ItemStack s) { return s.getItem() instanceof BlockItem; }

    /** 0 empty, 1 pickaxe, 2 axe, 3 sword, 4 food, 5 block, 6 other - as bot.js heldClass. */
    static int heldClass(LocalPlayer p) {
        ItemStack h = p.getMainHandItem();
        if (h.isEmpty()) return 0;
        String n = key(h);
        if (n.endsWith("_pickaxe")) return 1;
        if (n.endsWith("_axe")) return 2;
        if (n.endsWith("_sword")) return 3;
        if (isFood(h)) return 4;
        if (isBlock(h)) return 5;
        return 6;
    }

    /** Inventory index (0..35) of the best item matching, or -1. */
    static int find(LocalPlayer p, Predicate<ItemStack> which, java.util.function.ToIntFunction<ItemStack> rank) {
        int best = -1, br = Integer.MIN_VALUE;
        var items = p.getInventory().items;
        for (int i = 0; i < items.size(); i++) {
            ItemStack s = items.get(i);
            if (s.isEmpty() || !which.test(s)) continue;
            int r = rank == null ? 0 : rank.applyAsInt(s);
            if (best < 0 || r > br) { best = i; br = r; }
        }
        return best;
    }

    static int find(LocalPlayer p, Predicate<ItemStack> which) { return find(p, which, null); }

    static int findNamed(LocalPlayer p, Pattern name) { return find(p, s -> name.matcher(key(s)).find()); }

    /** The menu slot (index) that shows inventory index i in the open menu, or -1. */
    static int menuSlot(LocalPlayer p, AbstractContainerMenu menu, int inv) {
        for (Slot s : menu.slots) if (s.container == p.getInventory() && s.getContainerSlot() == inv) return s.index;
        return -1;
    }

    static void click(Minecraft mc, int slot, int button, ClickType type) {
        AbstractContainerMenu menu = mc.player.containerMenu;
        mc.gameMode.handleInventoryMouseClick(menu.containerId, slot, button, type, mc.player);
    }

    /** Take inventory item i into the main hand: select it on the hotbar, or swap it there. */
    static boolean hold(Minecraft mc, int inv) {
        LocalPlayer p = mc.player;
        if (inv < 0) return false;
        if (inv < 9) {
            p.getInventory().setSelectedHotbarSlot(inv);
            return true;
        }
        if (p.containerMenu != p.inventoryMenu) return false;
        int slot = menuSlot(p, p.inventoryMenu, inv);
        if (slot < 0) return false;
        click(mc, slot, p.getInventory().selected, ClickType.SWAP);
        return true;
    }

    static int count(LocalPlayer p, String name) {
        int n = 0;
        for (ItemStack s : p.getInventory().items) if (key(s).equals(name)) n += s.getCount();
        return n;
    }

    static BlockPos near(Minecraft mc, Predicate<String> name, int r) {
        BlockPos p = mc.player.blockPosition();
        BlockPos best = null;
        double bd = Double.MAX_VALUE;
        for (BlockPos q : BlockPos.betweenClosed(p.offset(-r, -r, -r), p.offset(r, r, r))) {
            double d = q.distSqr(p);
            if (d < bd && d <= r * r && name.test(Senses.name(mc.level.getBlockState(q)))) { best = q.immutable(); bd = d; }
        }
        return best;
    }

    static BlockPos tableNear(Minecraft mc) { return near(mc, n -> n.equals("crafting_table"), 4); }

    // ------------------------------------------------------------------ the recipe book
    record Craft(String name, RecipeDisplayId id, boolean small) {}

    /** Things never held that the recipe book knows a recipe for (craft_new). */
    static List<String> newThings(Minecraft mc) {
        List<String> out = new ArrayList<>();
        out.add("#new");
        return out;
    }

    /**
     * What the recipe book says I can make right now, among the wanted names (null: anything; "#new":
     * never held; "#gear": tools and armour, best first). Big (3x3) recipes need a table within reach.
     */
    static List<Craft> craftable(Minecraft mc, List<String> wanted) {
        LocalPlayer p = mc.player;
        List<Craft> out = new ArrayList<>();
        if (p == null || mc.level == null) return out;
        StackedItemContents have = new StackedItemContents();
        p.getInventory().fillStackedContents(have);
        var ctx = SlotDisplayContext.fromLevel(mc.level);
        boolean table = tableNear(mc) != null;
        boolean anyNew = wanted != null && wanted.contains("#new");
        boolean gear = wanted != null && wanted.contains("#gear");
        for (RecipeCollection col : p.getRecipeBook().getCollections()) {
            for (RecipeDisplayEntry e : col.getRecipes()) {
                RecipeDisplay d = e.display();
                boolean small;
                if (d instanceof ShapedCraftingRecipeDisplay s) small = s.width() <= 2 && s.height() <= 2;
                else if (d instanceof ShapelessCraftingRecipeDisplay s) small = s.ingredients().size() <= 4;
                else continue;                                  // furnaces, stonecutters...: other hands
                if (!small && !table) continue;
                List<ItemStack> result = e.resultItems(ctx);
                if (result.isEmpty()) continue;
                String name = key(result.get(0));
                if (wanted != null) {
                    boolean ok = anyNew ? !Senses.everHeld.contains(name)
                        : gear ? GEAR_RE.matcher(name).find() : wanted.contains(name);
                    if (!ok) continue;
                }
                if (!e.canCraft(have)) continue;
                if (out.stream().anyMatch(c -> c.name().equals(name))) continue;
                out.add(new Craft(name, e.id(), small));
            }
        }
        if (gear) out.sort((a, b) -> gearValue(b.name()) - gearValue(a.name()));
        else if (wanted != null && !anyNew) out.sort((a, b) -> wanted.indexOf(a.name()) - wanted.indexOf(b.name()));
        return out;
    }
}
