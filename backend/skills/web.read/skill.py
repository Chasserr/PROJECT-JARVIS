from jarvis.skills.web_read import read_url


async def run(args, context):
    return await read_url(
        args["url"],
        settings=context.settings,
        max_chars=args.get("max_chars"),
    )
