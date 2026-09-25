package ai.synapse.minecraft.mixin;

import ai.synapse.minecraft.SynapseBody;
import net.minecraft.client.MouseHandler;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** The physical mouse cannot turn Synapse's head or use its hands; in the Esc menu it works as usual. */
@Mixin(MouseHandler.class)
public abstract class MouseHandlerMixin {
    @Inject(method = "onPress", at = @At("HEAD"), cancellable = true)
    private void synapse$handsOffButtons(long window, int button, int action, int modifiers, CallbackInfo callback) {
        if (SynapseBody.handsOff() && !SynapseBody.paused()) callback.cancel();
    }

    @Inject(method = "onScroll", at = @At("HEAD"), cancellable = true)
    private void synapse$handsOffScroll(long window, double horizontal, double vertical, CallbackInfo callback) {
        if (SynapseBody.handsOff() && !SynapseBody.paused()) callback.cancel();
    }

    @Inject(method = "onMove", at = @At("HEAD"), cancellable = true)
    private void synapse$handsOffLook(long window, double x, double y, CallbackInfo callback) {
        if (SynapseBody.handsOff() && !SynapseBody.paused()) callback.cancel();
    }
}
