const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const stackName = process.env.STACK_NAME || "PnrTranslationAssistantStack";
const region = process.env.AWS_REGION || process.env.AWS_DEFAULT_REGION || "us-east-1";
const rootDir = path.join(__dirname, "..");
const webDir = path.join(rootDir, "web");

function aws(args) {
  return execFileSync("aws", ["--region", region, ...args], {
    cwd: rootDir,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "inherit"],
  }).trim();
}

function stackOutput(name) {
  return aws([
    "cloudformation",
    "describe-stacks",
    "--stack-name",
    stackName,
    "--query",
    `Stacks[0].Outputs[?OutputKey=='${name}'].OutputValue|[0]`,
    "--output",
    "text",
  ]);
}

const instanceId = aws([
  "cloudformation",
  "describe-stack-resources",
  "--stack-name",
  stackName,
  "--query",
  "StackResources[?ResourceType=='AWS::EC2::Instance' && starts_with(LogicalResourceId, 'WebInstance')].PhysicalResourceId|[0]",
  "--output",
  "text",
]);
const apiUrl = stackOutput("ApiUrl");
const webUrl = stackOutput("WebUrl");
const idToken = process.env.PNR_ID_TOKEN || "";
const config = idToken
  ? `window.PNR_APP_CONFIG = { apiUrl: ${JSON.stringify(apiUrl)}, idToken: ${JSON.stringify(idToken)} };\n`
  : `window.PNR_APP_CONFIG = { apiUrl: ${JSON.stringify(apiUrl)} };\n`;

const files = {
  "index.html": fs.readFileSync(path.join(webDir, "index.html"), "utf8"),
  "styles.css": fs.readFileSync(path.join(webDir, "styles.css"), "utf8"),
  "app.js": fs.readFileSync(path.join(webDir, "app.js"), "utf8"),
  "config.js": config,
};

const commands = [
  "mkdir -p /usr/share/nginx/html",
  "for i in 1 2 3 4 5 6; do dnf install -y nginx && break || sleep 10; done",
  "systemctl enable nginx",
];

for (const [filename, content] of Object.entries(files)) {
  commands.push(`base64 -d > /usr/share/nginx/html/${filename} <<'PNR_WEB_B64'\n${Buffer.from(content).toString("base64")}\nPNR_WEB_B64`);
}

commands.push("systemctl restart nginx");
commands.push("systemctl is-active nginx");

const parametersPath = path.join(os.tmpdir(), `pnr-web-${Date.now()}.json`);
fs.writeFileSync(parametersPath, JSON.stringify({ commands }));

const commandId = aws([
  "ssm",
  "send-command",
  "--instance-ids",
  instanceId,
  "--document-name",
  "AWS-RunShellScript",
  "--parameters",
  `file://${parametersPath}`,
  "--query",
  "Command.CommandId",
  "--output",
  "text",
]);

for (let attempt = 0; attempt < 40; attempt += 1) {
  const result = JSON.parse(aws([
    "ssm",
    "get-command-invocation",
    "--command-id",
    commandId,
    "--instance-id",
    instanceId,
    "--query",
    "{Status:Status,Stdout:StandardOutputContent,Stderr:StandardErrorContent}",
    "--output",
    "json",
  ]));

  if (["Success", "Failed", "Cancelled", "TimedOut"].includes(result.Status)) {
    if (result.Status !== "Success") {
      throw new Error(`web deploy failed: ${result.Status}\n${result.Stderr || result.Stdout || ""}`);
    }
    console.log(`Published web files to ${instanceId}`);
    console.log(`WebUrl: ${webUrl}`);
    process.exit(0);
  }

  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 3000);
}

throw new Error(`web deploy command timed out: ${commandId}`);
