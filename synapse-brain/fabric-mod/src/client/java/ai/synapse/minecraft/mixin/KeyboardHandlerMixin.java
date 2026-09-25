package ai.synapse.minecraft.mixin;

import ai.synapse.minecraft.SynapseBody;
import net.minecraft.client.KeyboardHandler;
import org.lwjgl.glfw.GLFW;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** The body belongs to Synapse: the physical keyboard cannot move it. Esc still pauses. */
@Mixin(KeyboardHandler.class)
public abstract class KeyboardHandlerMixin {
    @Inject(method = "keyPress", at = @At("HEAD"), cancellable = true)
    private void synapse$handsOff(long window, int key, int scanCode, int action, int modifiers, CallbackInfo callback) {
        if (SynapseBody.handsOff() && key != GLFW.GLFW_KEY_ESCAPE) callback.cancel();
    }
}
