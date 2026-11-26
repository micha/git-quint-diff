{
  description = "Source-bound Quint behavior reviews across Git commits";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { nixpkgs, ... }:
    let
      eachSystem = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      tools = eachSystem (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          quint = pkgs.buildNpmPackage rec {
            pname = "quint-cli";
            version = "0.33.1";
            src = pkgs.fetchFromGitHub {
              owner = "quint-co";
              repo = "quint";
              tag = "v${version}";
              hash = "sha256-F0Yj9e+qTOlj6RzspvkEhilXC6pFHvISBRLgvJmon7I=";
            };
            sourceRoot = "${src.name}/quint";
            npmDepsHash = "sha256-Bk21CfCh1xsY1cIYnSQfxxcpVkRbBg5EfGbFvJlTcvE=";
            npmBuildScript = "compile";
            npmFlags = [ "--ignore-scripts" ];
          };
          # Quint 0.33.1 uses this distribution for both verification backends.
          apalacheVersion = "0.62.4";
          apalacheDist = pkgs.fetchurl {
            url = "https://github.com/apalache-mc/apalache/releases/download/v${apalacheVersion}/apalache.tgz";
            hash = "sha256-ishIhCLDDVUnNbrhG5Ki0BTY4C6GCHAqzAj5otipq7I=";
          };
          apalacheCache = pkgs.runCommand "quint-apalache-${apalacheVersion}" { } ''
            mkdir -p "$out/apalache-dist-${apalacheVersion}"
            tar -xf ${apalacheDist} -C "$out/apalache-dist-${apalacheVersion}"
          '';
          # The packaged translator and TLC do not use the SMT solver payloads.
          # Keep the unmodified distribution in the dev shell for the independent oracle.
          apalacheRuntime = pkgs.runCommand "git-quint-diff-apalache-${apalacheVersion}"
            { nativeBuildInputs = [ pkgs.python3 ]; } ''
            jar="apalache-dist-${apalacheVersion}/apalache/lib/apalache.jar"
            mkdir -p "$out/$(dirname "$jar")"
            python3 -B ${./packaging/repack-backend.py} "${apalacheCache}/$jar" "$out/$jar"
          '';
          quintPackage = "${quint}/lib/node_modules/@informalsystems/quint";
        in {
          inherit pkgs quint quintPackage apalacheCache apalacheRuntime;
        });
    in {
      packages = eachSystem (system:
        let inherit (tools.${system}) pkgs quintPackage apalacheRuntime;
        in {
          default = pkgs.stdenvNoCC.mkDerivation {
            pname = "git-quint-diff";
            version = "0.1.0-rc1";
            src = pkgs.lib.fileset.toSource {
              root = ./.;
              fileset = pkgs.lib.fileset.unions [ ./LICENSE ./git-quint-diff ./runtime ];
            };
            nativeBuildInputs = [ pkgs.makeWrapper ];
            dontBuild = true;
            installPhase = ''
              runHook preInstall
              install -Dm644 git-quint-diff "$out/libexec/git-quint-diff/git-quint-diff"
              install -Dm644 LICENSE "$out/share/licenses/git-quint-diff/LICENSE"
              cp -r runtime "$out/libexec/git-quint-diff/"
              makeWrapper ${pkgs.nodejs}/bin/node "$out/bin/git-quint-diff" \
                --add-flags "$out/libexec/git-quint-diff/git-quint-diff" \
                --set QUINT_DIFF_QUINT_PACKAGE '${quintPackage}' \
                --set QUINT_HOME '${apalacheRuntime}' \
                --set QUINT_DIFF_JAVA '${pkgs.jdk_headless}/bin/java' \
                --unset NODE_OPTIONS --unset NODE_PATH \
                --unset JDK_JAVA_OPTIONS --unset JAVA_TOOL_OPTIONS --unset _JAVA_OPTIONS
              runHook postInstall
            '';
            meta = {
              description = "Compare the behavior of Quint models in two Git revisions";
              license = pkgs.lib.licenses.mit;
              mainProgram = "git-quint-diff";
            };
          };
        });
      devShells = eachSystem (system:
        let inherit (tools.${system}) pkgs quint quintPackage apalacheCache;
        in {
          default = pkgs.mkShell {
            packages = [ pkgs.git pkgs.jdk_headless pkgs.nodejs pkgs.python3 quint ];
            QUINT_HOME = apalacheCache;
            QUINT_DIFF_QUINT_PACKAGE = quintPackage;
          };
        });
    };
}
