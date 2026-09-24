// Preview-only stand-in for expo-status-bar. The real web implementation also
// renders nothing; this one additionally records the requested style so the
// preview frame (and the agent) can see what the model inferred.
import { useEffect } from 'react';

function record(patch) {
  const meta = (window.__RN_PREVIEW_META__ = window.__RN_PREVIEW_META__ || {});
  meta.statusBar = Object.assign({}, meta.statusBar, patch);
}

export function StatusBar(props) {
  const { style = 'auto', hidden = false, backgroundColor, translucent } = props || {};
  useEffect(() => {
    record({ style, hidden, backgroundColor, translucent });
  }, [style, hidden, backgroundColor, translucent]);
  return null;
}

export function setStatusBarStyle(style) {
  record({ style });
}
export function setStatusBarHidden(hidden) {
  record({ hidden });
}
export function setStatusBarBackgroundColor(backgroundColor) {
  record({ backgroundColor });
}
export function setStatusBarTranslucent(translucent) {
  record({ translucent });
}
export function setStatusBarNetworkActivityIndicatorVisible() {}
