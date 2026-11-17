// Include the actual license texts for all bundled production dependencies.
import { readFile, readdir, writeFile } from "node:fs/promises";
const lock = JSON.parse(
  await readFile(new URL("../package-lock.json", import.meta.url)),
);
const notices = ["Thesis Ledger frontend — third-party notices"];
for (const [path, entry] of Object.entries(lock.packages)) {
  if (!path || entry.dev) continue;
  const directory = new URL("../" + path + "/", import.meta.url);
  const pkg = JSON.parse(await readFile(new URL("package.json", directory)));
  const licenses = (await readdir(directory)).filter((name) =>
    /^(license|copying)([.-]|$)/i.test(name),
  );
  if (!licenses.length) throw Error("Missing license text for " + pkg.name);
  notices.push(
    "\n" +
      "=".repeat(72) +
      "\n" +
      pkg.name +
      " " +
      pkg.version +
      " (" +
      pkg.license +
      ")",
  );
  for (const file of licenses)
    notices.push(await readFile(new URL(file, directory), "utf8"));
}
await writeFile(
  new URL("../../ledger/web/react/THIRD_PARTY_NOTICES.txt", import.meta.url),
  notices.join("\n"),
);
