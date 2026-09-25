package ai.synapse.minecraft.mixin;

import net.minecraft.world.entity.projectile.FishingHook;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;

/** The float dips when a fish bites: the hand feels the line tug. */
@Mixin(FishingHook.class)
public interface FishingHookAccessor {
    @Accessor("biting")
    boolean synapse$isBiting();
}
