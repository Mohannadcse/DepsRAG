CONSTRUCT_DEPENDENCY_GRAPH_OLD = """
        with "{package_type}" as system, "{package_name}" as name, "{package_version}" as version

        call apoc.load.json("https://api.deps.dev/v3alpha/systems/"+apoc.text.urlencode(system)+"/packages/"
                            +apoc.text.urlencode(name)+"/versions/"+apoc.text.urlencode(version)+":dependencies")
        yield value as r

        call {{ with r
                unwind r.nodes as package
                merge (p:Package:{package_type_system} {{name: package.versionKey.name, version: package.versionKey.version}})
                return collect(p) as packages
        }}
        call {{ with r, packages
            unwind r.edges as edge
            with packages[edge.fromNode] as from, packages[edge.toNode] as to, edge
            merge (from)-[rel:DEPENDS_ON]->(to) ON CREATE SET rel.requirement
            = edge.requirement
            return count(*) as numRels
        }}

        match (root:Package:{package_type_system}) where root.imported is null
        set root.imported = true
        with "{package_type}" as system, root.name as name, root.version as version
        call apoc.load.json("https://api.deps.dev/v3alpha/systems/"+apoc.text.urlencode(system)+"/packages/"
                            +apoc.text.urlencode(name)+"/versions/"+apoc.text.urlencode(version)+":dependencies")
        yield value as r

        call {{ with r
                unwind r.nodes as package
                merge (p:Package:{package_type_system} {{name: package.versionKey.name, version: package.versionKey.version}})
                return collect(p) as packages
        }}
        call {{ with r, packages
                unwind r.edges as edge
                with packages[edge.fromNode] as from, packages[edge.toNode] as to, edge
                merge (from)-[rel:DEPENDS_ON]->(to) ON CREATE SET
                rel.requirement = edge.requirement
                return count(*) as numRels
        }}
        return size(packages) as numPackages, numRels
        """

CONSTRUCT_DEPENDENCY_GRAPH = """
    call apoc.load.json("{url}") yield value as packageData
    unwind packageData as pkg
    with pkg.package_name as packageName,
         pkg.package_version as packageVersion,
         pkg.main_package_size as mainPackageSize,
         pkg.total_size as totalSize,
         pkg.native_modules as nativeModules,
         pkg.error as error,
         pkg.edges as edges,
         pkg.root as isRoot

    // Create or update the package node (ensure consistent 'Package' label)
    merge (pkg:Package {{name: packageName, version: packageVersion}})
    on create set 
        pkg.main_package_size = mainPackageSize,
        pkg.total_size = totalSize,
        pkg.native_modules = nativeModules,
        pkg.error = error,
        pkg.root = isRoot
    on match set 
        pkg.root = isRoot

    with pkg, edges
    unwind edges as edge
    with pkg, edge.from as fromNode, edge.to as toNode, edge.requirement as requirement

    // Create or update the "from" and "to" nodes and the relationship
    merge (fromPkg:Package {{name: fromNode.name, version: fromNode.version}})
    merge (toPkg:Package {{name: toNode.name, version: toNode.version}})
    merge (fromPkg)-[dep:DEPENDS_ON]->(toPkg)
    on create set dep.requirement = requirement

    // Carry results to the RETURN clause
    with pkg, dep
    return count(distinct pkg) as numNodes, count(distinct dep) as numEdges;
"""
