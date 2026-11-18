import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.elliewells.nexus',
  appName: 'Nexus',
  webDir: 'dist',
  // The web build is bundled into the Android app, so there is no remote
  // server URL. The local bundle is served over plain HTTP (server.androidScheme)
  // so fetching a self-hosted server over plain HTTP on a LAN/Tailscale is not
  // blocked as mixed content. Cleartext traffic is allowed too. Users are
  // advised to use HTTPS for public access.
  server: {
    cleartext: true,
    androidScheme: 'http',
  },
  android: {
    // Allow the Web View to fetch plain-HTTP server URLs even when the local
    // bundle is served over HTTPS (defense in depth).
    allowMixedContent: true,
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 600,
      backgroundColor: '#141218',
      showSpinner: false,
      androidScaleType: 'CENTER_CROP',
    },
    StatusBar: {
      backgroundColor: '#141218',
      style: 'DARK',
      webViewStyle: 'DARK_CONTENT',
    },
    Keyboard: {
      resize: 'body',
      style: 'DARK',
    },
  },
};

export default config;
