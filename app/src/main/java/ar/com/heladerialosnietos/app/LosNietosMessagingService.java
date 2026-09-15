package ar.com.heladerialosnietos.app;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.graphics.Color;
import android.os.Build;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

public class LosNietosMessagingService extends FirebaseMessagingService {
    private static final String CHANNEL_ID = "club_puntos";

    @Override
    public void onNewToken(String token) {
        super.onNewToken(token);
        getSharedPreferences("push", MODE_PRIVATE).edit().putString("token", token).apply();
    }

    @Override
    public void onMessageReceived(RemoteMessage message) {
        super.onMessageReceived(message);
        String title = "Heladería Los Nietos";
        String body = "Tenés una novedad en tu cuenta.";
        if (message.getNotification() != null) {
            if (message.getNotification().getTitle() != null) title = message.getNotification().getTitle();
            if (message.getNotification().getBody() != null) body = message.getNotification().getBody();
        }
        if (message.getData().containsKey("title")) title = message.getData().get("title");
        if (message.getData().containsKey("body")) body = message.getData().get("body");
        String url = message.getData().getOrDefault("url", "/club/cuenta");
        showNotification(title, body, url);
    }

    private void showNotification(String title, String body, String url) {
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(CHANNEL_ID, "Puntos y compras", NotificationManager.IMPORTANCE_HIGH);
            channel.setDescription("Avisos de puntos, compras y novedades de Heladería Los Nietos");
            channel.enableLights(true);
            channel.setLightColor(Color.rgb(79, 43, 216));
            manager.createNotificationChannel(channel);
        }

        Intent intent = new Intent(this, MainActivity.class);
        intent.putExtra("url", url);
        intent.setFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pending = PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        android.app.Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new android.app.Notification.Builder(this, CHANNEL_ID)
                : new android.app.Notification.Builder(this);
        builder.setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new android.app.Notification.BigTextStyle().bigText(body))
                .setAutoCancel(true)
                .setContentIntent(pending)
                .setPriority(android.app.Notification.PRIORITY_HIGH);
        manager.notify((int) (System.currentTimeMillis() & 0x0fffffff), builder.build());
    }
}
