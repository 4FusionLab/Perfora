// SPDX-License-Identifier: GPL-3.0-only
let runtime;
self.onmessage = async ({data}) => {
  try {
    if (data.type === 'init') {
      importScripts('https://cdn.jsdelivr.net/pyodide/v0.27.7/full/pyodide.js');
      runtime = await loadPyodide({indexURL:'https://cdn.jsdelivr.net/pyodide/v0.27.7/full/'});
      for (const [path, source] of Object.entries(data.sources)) {
        const directory = '/app/' + path.split('/').slice(0,-1).join('/');
        runtime.FS.mkdirTree(directory);
        runtime.FS.writeFile('/app/' + path, source, {encoding:'utf8'});
      }
      await runtime.runPythonAsync("import sys\nsys.path.insert(0, '/app')\nfrom demo.engine import compute_json");
      self.postMessage({type:'ready'});
    } else if (data.type === 'compute') {
      runtime.globals.set('demo_request', JSON.stringify(data.parameters));
      const result = JSON.parse(await runtime.runPythonAsync('compute_json(demo_request)'));
      self.postMessage({type:'result', id:data.id, result});
    }
  } catch (error) {
    self.postMessage({type:'error', id:data.id, message:String(error.message || error)});
  }
};
