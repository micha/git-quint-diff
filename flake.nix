{
  description = "Source-bound Quint behavior reviews across Git commits";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs, ... }:
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
          inherit pkgs quint quintPackage apalacheCache apalacheRuntime apalacheVersion;
        });
    in {
      packages = eachSystem (system:
        let
          inherit (tools.${system}) pkgs quintPackage apalacheCache apalacheRuntime apalacheVersion;
          payloads = builtins.fromJSON (builtins.readFile ./packaging/payloads.json);
          runtimeNotices = pkgs.linkFarm "git-quint-diff-runtime-notices"
            (pkgs.lib.mapAttrsToList (name: pin: {
              inherit name;
              path = pkgs.fetchurl {
                url = builtins.elemAt pin 0;
                sha256 = builtins.elemAt pin 1;
              };
            }) payloads.notice_files);
          tlcRevision = payloads.tlc_source.revision;
          tlcUpstream = pkgs.fetchurl {
            url = "https://codeload.github.com/tlaplus/tlaplus/tar.gz/${tlcRevision}";
            sha256 = payloads.tlc_source.upstream_sha256;
          };
          tlcPack = pkgs.lib.fileset.toSource {
            root = ./packaging;
            fileset = pkgs.lib.fileset.unions [ ./packaging/tlc_source.py ./packaging/payloads.json ];
          };
          jvmLegal = pkgs.lib.fileset.toSource {
            root = ./packaging;
            fileset = pkgs.lib.fileset.unions [ ./packaging/jvm_legal.py ./packaging/jvm-legal ];
          };
          jvmSources = builtins.fromJSON (builtins.readFile ./packaging/jvm-legal/sources.json);
          sourceInputs = pkgs.linkFarm "git-quint-diff-jvm-source-inputs"
            (pkgs.lib.mapAttrsToList (name: pin: {
              inherit name;
              path = pkgs.fetchurl { inherit (pin) url sha256; };
            }) jvmSources.inputs);
        in {
          # Match the wheel's filtered JVM and TLC source tars without retaining them at runtime.
          jvm-source-companions = pkgs.runCommand "git-quint-diff-jvm-source-companions"
            { nativeBuildInputs = [ pkgs.python3 ]; } ''
              python3 -B ${jvmLegal}/jvm_legal.py pack ${sourceInputs} "$out"
              python3 -B ${tlcPack}/tlc_source.py pack ${tlcUpstream} "$out/tlaplus-${tlcRevision}-source.tar"
            '';
          default = pkgs.stdenvNoCC.mkDerivation {
            pname = "git-quint-diff";
            version = "0.1.0-rc1";
            src = pkgs.lib.fileset.toSource {
              root = ./.;
              fileset = pkgs.lib.fileset.unions [ ./LICENSE ./git-quint-diff ./runtime ];
            };
            nativeBuildInputs = [ pkgs.makeWrapper pkgs.python3 ];
            dontBuild = true;
            installPhase = ''
              runHook preInstall
              install -Dm644 git-quint-diff "$out/libexec/git-quint-diff/git-quint-diff"
              legal="$out/share/licenses/git-quint-diff"
              install -Dm644 LICENSE "$legal/LICENSE"
              apalache=${apalacheCache}/apalache-dist-${apalacheVersion}/apalache
              install -m644 "$apalache/LICENSE" "$legal/Apalache-LICENSE"
              for notice in ${runtimeNotices}/*; do
                install -m644 "$notice" "$legal/$(basename "$notice")"
              done
              install -m644 ${./packaging/TLC-SOURCE.md} "$legal/TLC-SOURCE.md"
              python3 -B ${jvmLegal}/jvm_legal.py install "$legal/jvm"
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
      apps = eachSystem (system:
        let
          inherit (tools.${system}) pkgs;
          demoSource = pkgs.lib.fileset.toSource {
            root = ./.;
            fileset = pkgs.lib.fileset.unions [
              ./docs/consensus-review.json
              ./release-tests/demo-consensus.py
              ./release-tests/consensus_fixture.py
              ./release-tests/fixtures/consensus
            ];
          };
          demo = pkgs.writeShellApplication {
            name = "git-quint-diff-demo";
            runtimeInputs = [ pkgs.git pkgs.python3 ];
            text = ''
              exec python3 -B ${demoSource}/release-tests/demo-consensus.py \
                ${self.packages.${system}.default}/bin/git-quint-diff
            '';
          };
        in {
          demo = {
            type = "app";
            program = "${demo}/bin/git-quint-diff-demo";
            meta.description = "Review the bundled upstream Quint consensus example";
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
