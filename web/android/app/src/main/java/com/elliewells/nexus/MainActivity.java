package com.elliewells.nexus;

import android.os.Bundle;
import android.view.View;
import android.view.Window;
import android.webkit.WebView;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
  @Override
  protected void onCreate(Bundle savedInstanceState) {
    WebView.setWebContentsDebuggingEnabled(true);
    super.onCreate(savedInstanceState);

    Window window = getWindow();
    // Edge-to-edge so the status / navigation bars can be colored to match the app.
    window.setDecorFitsSystemWindows(false);
    window.setStatusBarColor(0xFF141218);
    window.setNavigationBarColor(0xFF141218);

    // Pad the content root so the web view never renders underneath the bars.
    ViewCompat.setOnApplyWindowInsetsListener(
        findViewById(android.R.id.content),
        (v, insets) -> {
          Insets bars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
          v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
          return WindowInsetsCompat.CONSUMED;
        });
  }
}
