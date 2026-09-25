package ai.synapse.minecraft.mixin;

import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * The whole game at the world's pace. Vanilla lets the client follow the server's /tick rate only when it is
 * SLOWER than normal (Math.max(50 ms, ms per tick)): at /tick rate 60 the mobs and the days hurry, but the
 * player still walks and digs at 20 ticks a second. Here the client ticks as fast as the world, so Synapse's
 * legs and hands keep pace with everything else.
 */
@Mixin(Minecraft.class)
public abstract class MinecraftTickRateMixin {
    @Inject(method = "getTickTargetMillis", at = @At("HEAD"), cancellable = true)
    private void synapse$followTheWorldsPace(float normal, CallbackInfoReturnable<Float> callback) {
        var level = ((Minecraft) (Object) this).level;
        if (level != null && level.tickRateManager().runsNormally()) {
            callback.setReturnValue(level.tickRateManager().millisecondsPerTick());
        }
    }
}
