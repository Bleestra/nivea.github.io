package ai.synapse.minecraft.mixin;

import ai.synapse.minecraft.Senses;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.network.protocol.game.ClientboundBlockDestructionPacket;
import net.minecraft.network.protocol.game.ClientboundBlockUpdatePacket;
import net.minecraft.network.protocol.game.ClientboundDamageEventPacket;
import net.minecraft.network.protocol.game.ClientboundExplodePacket;
import net.minecraft.network.protocol.game.ClientboundTakeItemEntityPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Hearing and touch the game only tells the network layer about: explosions, and picking things up. */
@Mixin(ClientPacketListener.class)
public abstract class ClientPacketListenerMixin {
    @Inject(method = "handleExplosion", at = @At("HEAD"))
    private void synapse$heardExplosion(ClientboundExplodePacket packet, CallbackInfo callback) {
        Senses.heardExplosion(packet.center());
    }

    @Inject(method = "handleTakeItemEntity", at = @At("HEAD"))
    private void synapse$pickedUp(ClientboundTakeItemEntityPacket packet, CallbackInfo callback) {
        Senses.pickedUp(packet.getPlayerId());
    }

    // (a handler runs twice: first on the network thread, which only hands it over, then on the game thread)

    /** Pain and its cause: the game says what kind of damage it was (a fall, a blow, hunger...) and from whom. */
    @Inject(method = "handleDamageEvent", at = @At("HEAD"))
    private void synapse$damage(ClientboundDamageEventPacket packet, CallbackInfo callback) {
        if (!Minecraft.getInstance().isSameThread()) return;
        String type = packet.sourceType().unwrapKey().map(k -> k.location().getPath()).orElse("generic");
        Senses.damaged(packet.entityId(), type, packet.sourceCauseId());
    }

    /** Someone else is breaking a block (the cracks I see on it). */
    @Inject(method = "handleBlockDestruction", at = @At("HEAD"))
    private void synapse$othersBreaking(ClientboundBlockDestructionPacket packet, CallbackInfo callback) {
        if (!Minecraft.getInstance().isSameThread()) return;
        Senses.othersBreaking(packet.getId(), packet.getPos(), packet.getProgress());
    }

    /** A block is about to change (the old one is still there): broken or placed by someone near. */
    @Inject(method = "handleBlockUpdate", at = @At("HEAD"))
    private void synapse$blockChanging(ClientboundBlockUpdatePacket packet, CallbackInfo callback) {
        if (!Minecraft.getInstance().isSameThread()) return;
        Senses.blockChanging(packet.getPos(), packet.getBlockState());
    }
}
