package ar.com.heladerialosnietos.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.ValueCallback;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.ProgressBar;
import android.widget.LinearLayout;

import com.google.firebase.messaging.FirebaseMessaging;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.nio.charset.Charset;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.List;

import java.net.URI;

public class MainActivity extends Activity {
    private static final int NOTIFICATION_PERMISSION_CODE = 7001;
    private WebView webView;
    private ProgressBar progress;
    private LinearLayout offlinePanel;
    private String fcmToken = "";
    private ValueCallback<Uri[]> filePathCallback;
    private static final int FILE_CHOOSER_CODE = 7002;
    private static final String RAWBT_PACKAGE = "ru.a402d.rawbtprinter";
    private static final String RAWBT_ACTION = "ru.a402d.rawbtprinter.action.PRINT_RAWBT";
    private static final String RAWBT_EXTRA = "ru.a402d.rawbtprinter.extra.DATA";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        webView = findViewById(R.id.webView);
        progress = findViewById(R.id.progress);
        offlinePanel = findViewById(R.id.offlinePanel);
        Button retry = findViewById(R.id.retryButton);
        retry.setOnClickListener(v -> loadPortal());

        configureWebView();
        if (BuildConfig.ENABLE_CLUB_PUSH) {
            askNotificationPermissionIfNeeded();
            loadFcmToken();
        }

        String fromNotification = getIntent().getStringExtra("url");
        if (fromNotification != null && !fromNotification.trim().isEmpty()) {
            webView.loadUrl(absolutePortalUrl(fromNotification));
        } else {
            loadPortal();
        }
    }

    private void configureWebView() {
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setUserAgentString(s.getUserAgentString() + " HeladeriaLosNietosAndroid/1.0");

        webView.addJavascriptInterface(new RawBtBridge(), "AndroidRawBT");

        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                progress.setProgress(newProgress);
                progress.setVisibility(newProgress >= 100 ? View.GONE : View.VISIBLE);
            }

            @Override
            public boolean onShowFileChooser(WebView webView, ValueCallback<Uri[]> filePathCallbackNew, FileChooserParams fileChooserParams) {
                if (filePathCallback != null) filePathCallback.onReceiveValue(null);
                filePathCallback = filePathCallbackNew;
                try {
                    Intent chooser = fileChooserParams.createIntent();
                    startActivityForResult(chooser, FILE_CHOOSER_CODE);
                    return true;
                } catch (Exception e) {
                    filePathCallback = null;
                    return false;
                }
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                offlinePanel.setVisibility(View.GONE);
                webView.setVisibility(View.VISIBLE);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                registerPushTokenInPortal();
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return handleUrl(request.getUrl().toString());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleUrl(url);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (!request.isForMainFrame()) return;
                String failingUrl = request.getUrl() == null ? "" : request.getUrl().toString();
                if (failingUrl.startsWith("rawbt:") || failingUrl.startsWith("intent:")) {
                    offlinePanel.setVisibility(View.GONE);
                    webView.setVisibility(View.VISIBLE);
                    return;
                }
                showOffline();
            }
        });
    }

    private boolean handleUrl(String url) {
        if (url == null) return false;
        if (url.startsWith("rawbt:")) {
            String payload = url.substring("rawbt:".length());
            try { payload = Uri.decode(payload); } catch (Exception ignored) {}
            sendToRawBt(payload);
            return true;
        }
        if (url.startsWith("intent:")) {
            try {
                Intent intent = Intent.parseUri(url, Intent.URI_INTENT_SCHEME);
                startActivity(intent);
            } catch (Exception ignored) {}
            return true;
        }
        if (url.startsWith("mercadopago://") || isMercadoPagoUrl(url)) {
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                return true;
            } catch (Exception ignored) {
                return false;
            }
        }
        if (url.startsWith("tel:") || url.startsWith("mailto:") || url.startsWith("geo:")) {
            try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); } catch (Exception ignored) {}
            return true;
        }
        return false;
    }

    private static byte[] b(int... values) {
        byte[] out = new byte[values.length];
        for (int i = 0; i < values.length; i++) out[i] = (byte) values[i];
        return out;
    }

    private static String asciiSafe(String value) {
        if (value == null) return "";
        String n = Normalizer.normalize(value, Normalizer.Form.NFD)
                .replaceAll("\\p{M}+", "");
        return n.replace('ñ', 'n').replace('Ñ', 'N')
                .replace('¡', ' ').replace('¿', ' ');
    }

    private static List<String> wrap32(String src) {
        List<String> out = new ArrayList<>();
        String text = src == null ? "" : src.trim();
        if (text.length() <= 32) {
            out.add(text);
            return out;
        }
        while (text.length() > 32) {
            int cut = text.lastIndexOf(' ', 32);
            if (cut < 10) cut = 32;
            out.add(text.substring(0, cut).trim());
            text = text.substring(cut).trim();
        }
        out.add(text);
        return out;
    }

    private static boolean isSeparator(String line) {
        String t = line == null ? "" : line.trim();
        return t.matches("[-=_]{8,}");
    }

    private static boolean looksLikeDate(String line) {
        String t = line == null ? "" : line.trim();
        return t.matches(".*\\d{4}[-/]\\d{2}[-/]\\d{2}.*") || t.matches(".*\\d{2}[-/]\\d{2}[-/]\\d{4}.*");
    }

    private static boolean isImportantTitle(String upper) {
        return upper.contains("TICKET DE VENTA")
                || upper.contains("ANULACION DE TICKET")
                || upper.contains("CIERRE DE CAJA")
                || upper.contains("APERTURA DE CAJA")
                || upper.contains("COMPROBANTE DE FIDELIDAD")
                || upper.startsWith("PEDIDO")
                || upper.contains("PRUEBA RAWBT");
    }

    private static void writeBytes(ByteArrayOutputStream out, byte[] data) {
        try { out.write(data); } catch (Exception ignored) {}
    }

    private static void writeText(ByteArrayOutputStream out, String text) {
        try {
            // CP850 es ampliamente compatible con impresoras ESC/POS genéricas.
            out.write(asciiSafe(text).getBytes(Charset.forName("CP850")));
        } catch (Exception e) {
            try { out.write(asciiSafe(text).getBytes()); } catch (Exception ignored) {}
        }
    }

    private static void style(ByteArrayOutputStream out, int align, boolean bold, int size) {
        // ESC a n: 0 izquierda, 1 centro, 2 derecha
        writeBytes(out, b(0x1B, 0x61, align));
        // ESC E n: negrita
        writeBytes(out, b(0x1B, 0x45, bold ? 1 : 0));
        // GS ! n: tamaño. 0x01 = doble alto; 0x11 = doble ancho+alto
        writeBytes(out, b(0x1D, 0x21, size));
    }

    private static void line(ByteArrayOutputStream out, String text, int align, boolean bold, int size) {
        style(out, align, bold, size);
        writeText(out, text);
        writeBytes(out, b(0x0A));
    }

    /**
     * Convierte el ticket de texto generado por Clouding en un ticket ESC/POS real de 58 mm.
     * RawBT recibe bytes listos para la impresora, por lo que conserva centrado, negrita,
     * tamaño del TOTAL y ancho de 32 columnas.
     */
    private static byte[] buildEscPos58(String source) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        // Inicializar y seleccionar CP850.
        writeBytes(out, b(0x1B, 0x40));
        writeBytes(out, b(0x1B, 0x74, 0x02));

        String normalized = (source == null ? "" : source).replace("\r\n", "\n").replace('\r', '\n');
        String[] rows = normalized.split("\\n", -1);
        boolean beforeFirstSeparator = true;
        boolean storePrinted = false;

        for (String raw : rows) {
            String t = raw == null ? "" : raw.trim();
            if (t.isEmpty()) {
                style(out, 0, false, 0x00);
                writeBytes(out, b(0x0A));
                continue;
            }
            String upper = asciiSafe(t).toUpperCase();

            if (isSeparator(t)) {
                beforeFirstSeparator = false;
                line(out, "--------------------------------", 0, false, 0x00);
                continue;
            }

            // Primera línea: nombre del comercio. Doble alto, no doble ancho para no cortarlo.
            if (!storePrinted) {
                line(out, t, 1, true, 0x01);
                storePrinted = true;
                continue;
            }

            if (isImportantTitle(upper) || upper.startsWith("***")) {
                for (String part : wrap32(t)) line(out, part, 1, true, 0x01);
                continue;
            }

            if (looksLikeDate(t)) {
                line(out, t, 1, false, 0x00);
                continue;
            }

            if (upper.startsWith("TOTAL") || upper.contains("TOTAL ANULADO")) {
                for (String part : wrap32(t)) line(out, part, 0, true, 0x01);
                continue;
            }

            if (upper.startsWith("PAGO:") || upper.startsWith("VUELTO") || upper.startsWith("RECIBIDO")
                    || upper.startsWith("PUNTOS ") || upper.contains("CANJE DE PUNTOS")) {
                for (String part : wrap32(t)) line(out, part, 0, true, 0x00);
                continue;
            }

            if (upper.equals("SISTEMA HELADERIA") || upper.contains("GRACIAS POR SU COMPRA")) {
                for (String part : wrap32(t)) line(out, part, 1, true, 0x00);
                continue;
            }

            // Dirección/teléfono antes del primer separador centrados como encabezado.
            if (beforeFirstSeparator) {
                for (String part : wrap32(t)) line(out, part, 1, false, 0x00);
                continue;
            }

            // Resto del ticket: ancho fijo 32 columnas.
            for (String part : wrap32(t)) line(out, part, 0, false, 0x00);
        }

        style(out, 0, false, 0x00);
        writeBytes(out, b(0x0A, 0x0A, 0x0A, 0x0A));
        return out.toByteArray();
    }

    /** V46: recibe los bytes ESC/POS ya generados por Clouding con el MISMO formato del sistema central. */
    private void sendBase64ToRawBt(String base64Payload) {
        final String b64 = base64Payload == null ? "" : base64Payload.trim();
        if (b64.isEmpty()) return;
        runOnUiThread(() -> {
            try {
                Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse("rawbt:base64," + b64));
                intent.setPackage(RAWBT_PACKAGE);
                startActivity(intent);
                return;
            } catch (Exception ignored) {}
            try {
                Intent intent = new Intent(RAWBT_ACTION);
                intent.putExtra(RAWBT_EXTRA, "base64," + b64);
                intent.setPackage(RAWBT_PACKAGE);
                startActivity(intent);
            } catch (Exception ignored) {}
        });
    }

    private void sendToRawBt(String text) {
        final String payload = text == null ? "" : text;
        runOnUiThread(() -> {
            // V45: enviar RAW ESC/POS en base64. Es el método oficial para conservar formato.
            try {
                byte[] escpos = buildEscPos58(payload);
                String base64 = android.util.Base64.encodeToString(escpos, android.util.Base64.NO_WRAP);
                Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse("rawbt:base64," + base64));
                intent.setPackage(RAWBT_PACKAGE);
                startActivity(intent);
                return;
            } catch (Exception ignored) {}

            // Fallback: acción específica RawBT con el mismo bloque binario codificado.
            try {
                byte[] escpos = buildEscPos58(payload);
                String base64 = "base64," + android.util.Base64.encodeToString(escpos, android.util.Base64.NO_WRAP);
                Intent intent = new Intent(RAWBT_ACTION);
                intent.putExtra(RAWBT_EXTRA, base64);
                intent.setPackage(RAWBT_PACKAGE);
                startActivity(intent);
                return;
            } catch (Exception ignored) {}

            // Último fallback: texto plano.
            try {
                Intent sendIntent = new Intent(Intent.ACTION_SEND);
                sendIntent.setType("text/plain");
                sendIntent.putExtra(Intent.EXTRA_TEXT, payload);
                sendIntent.setPackage(RAWBT_PACKAGE);
                startActivity(sendIntent);
                return;
            } catch (Exception ignored) {}

            try {
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=" + RAWBT_PACKAGE)));
            } catch (Exception ignored) {
                try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("https://play.google.com/store/apps/details?id=" + RAWBT_PACKAGE))); } catch (Exception ignored2) {}
            }
        });
    }

    private class RawBtBridge {
        @JavascriptInterface
        public void print(String text) {
            sendToRawBt(text);
        }

        @JavascriptInterface
        public void printBase64(String base64Payload) {
            sendBase64ToRawBt(base64Payload);
        }
    }

    private boolean isMercadoPagoUrl(String url) {
        try {
            URI uri = new URI(url);
            String host = uri.getHost();
            if (host == null) return false;
            host = host.toLowerCase();
            return host.endsWith("mercadopago.com") || host.endsWith("mercadopago.com.ar") || host.endsWith("mercadolibre.com");
        } catch (Exception e) {
            return false;
        }
    }

    private void loadPortal() {
        offlinePanel.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        webView.loadUrl(BuildConfig.PORTAL_URL);
    }

    private void showOffline() {
        webView.setVisibility(View.GONE);
        offlinePanel.setVisibility(View.VISIBLE);
    }

    private void loadFcmToken() {
        FirebaseMessaging.getInstance().getToken().addOnCompleteListener(task -> {
            if (!task.isSuccessful() || task.getResult() == null) return;
            fcmToken = task.getResult();
            getSharedPreferences("push", MODE_PRIVATE).edit().putString("token", fcmToken).apply();
            registerPushTokenInPortal();
        });
    }

    private void registerPushTokenInPortal() {
        if (!BuildConfig.ENABLE_CLUB_PUSH) return;
        if (webView == null) return;
        if (fcmToken == null || fcmToken.isEmpty()) {
            fcmToken = getSharedPreferences("push", MODE_PRIVATE).getString("token", "");
        }
        if (fcmToken.isEmpty()) return;
        String tokenJson = JSONObject.quote(fcmToken);
        String js = "(function(){" +
                "const t=" + tokenJson + ";" +
                "fetch('/club/api/push/register',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({token:t,platform:'ANDROID',device:'Heladeria Los Nietos'})}).catch(()=>{});" +
                "document.querySelectorAll('a[href*=\"/club/salir\"]').forEach(function(a){if(a.dataset.pushHook)return;a.dataset.pushHook='1';a.addEventListener('click',function(){fetch('/club/api/push/unregister',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',keepalive:true,body:JSON.stringify({token:t})}).catch(()=>{});});});" +
                "})();";
        webView.evaluateJavascript(js, null);
    }

    private String absolutePortalUrl(String path) {
        if (path.startsWith("http://") || path.startsWith("https://")) return path;
        try {
            URI base = new URI(BuildConfig.PORTAL_URL);
            return base.getScheme() + "://" + base.getAuthority() + (path.startsWith("/") ? path : "/" + path);
        } catch (Exception e) {
            return BuildConfig.PORTAL_URL;
        }
    }

    private void askNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, NOTIFICATION_PERMISSION_CODE);
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == FILE_CHOOSER_CODE && filePathCallback != null) {
            Uri[] results = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
            filePathCallback.onReceiveValue(results);
            filePathCallback = null;
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        String url = intent.getStringExtra("url");
        if (url != null && !url.isEmpty() && webView != null) webView.loadUrl(absolutePortalUrl(url));
    }

    @Override
    protected void onResume() {
        super.onResume();
        registerPushTokenInPortal();
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }
}
