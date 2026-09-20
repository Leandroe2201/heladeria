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

    private void sendToRawBt(String text) {
        final String payload = text == null ? "" : text;
        runOnUiThread(() -> {
            try {
                Intent intent = new Intent(RAWBT_ACTION);
                intent.putExtra(RAWBT_EXTRA, payload);
                intent.setPackage(RAWBT_PACKAGE);
                startActivity(intent);
                return;
            } catch (Exception ignored) {}

            try {
                Intent viewIntent = new Intent(Intent.ACTION_VIEW, Uri.parse("rawbt:" + payload));
                viewIntent.setPackage(RAWBT_PACKAGE);
                startActivity(viewIntent);
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
