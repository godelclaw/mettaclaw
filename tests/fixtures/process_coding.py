def transform(periphery):
    _, development, life, _coding, _active = periphery
    return [
        "three-policy-periphery",
        development,
        life,
        ["coding-state", "workspace-1", ["tool-result-observed"], "ready"],
        "coding",
    ]
