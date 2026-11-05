// Runs the Python engine off the main thread so the page stays responsive.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.27.7/full/pyodide.js");

let handle = null;

async function boot(zipUrl) {
  const py = await loadPyodide();
  const zip = await fetch(zipUrl);
  if (!zip.ok) throw new Error(`could not load ${zipUrl}: HTTP ${zip.status}`);
  py.unpackArchive(await zip.arrayBuffer(), "zip");
  py.runPython("import sys, os; sys.path.insert(0, os.getcwd())");
  handle = py.pyimport("viz.browser").handle;
}

// Messages are queued while boot runs, so handle is set before any later one is served.
let chain = Promise.resolve();
onmessage = ({ data }) => {
  chain = chain.then(async () => {
    try {
      if (data.boot) await boot(data.boot);
      postMessage({ rid: data.rid, result: handle(JSON.stringify(data.request)) });
    } catch (e) {
      postMessage({ rid: data.rid, error: String(e) });
    }
  });
};
