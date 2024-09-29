import {Typography, Space, Button} from "antd"
import {ArrowLeft, Check, Copy, Play} from "@phosphor-icons/react"
import {createUseStyles} from "react-jss"
import {JSSTheme} from "@/lib/Types"
import {isDemo} from "@/lib/helpers/utils"
import {useRouter} from "next/router"
import {useState} from "react"

const {Text} = Typography

const useStyles = createUseStyles((theme: JSSTheme) => ({
    modal: {
        display: "flex",
        flexDirection: "column",
        gap: 16,
    },
    headerText: {
        "& .ant-typography": {
            lineHeight: theme.lineHeightLG,
            fontSize: theme.fontSizeHeading4,
            fontWeight: theme.fontWeightStrong,
        },
    },
    label: {
        fontWeight: theme.fontWeightMedium,
    },
    command: {
        width: "92%",
        backgroundColor: "#f6f8fa",
        borderRadius: theme.borderRadius,
        border: "1px solid",
        borderColor: theme.colorBorder,
        color: theme.colorText,
        cursor: "default",
        padding: "3.5px 11px",
    },
    copyBtn: {
        width: theme.controlHeight,
        height: theme.controlHeight,
        "& > .ant-btn-icon": {
            marginTop: 2,
            marginLeft: 1,
        },
    },
}))

type Props = {
    setCurrent: React.Dispatch<React.SetStateAction<number>>
    hasApps: boolean
}

const WriteOwnAppModal = ({setCurrent, hasApps}: Props) => {
    const classes = useStyles()
    const router = useRouter()
    const [isCopied, setIsCopied] = useState<number | null>(null)

    const onCopyCode = (code: string, index: number) => {
        navigator.clipboard.writeText(code)
        setIsCopied(index)

        setTimeout(() => setIsCopied(null), 2000)
    }
    const listOfCommands = [
        ...(isDemo()
            ? [
                  {
                      title: "Add an API Key",
                      code: "",
                  },
              ]
            : []),
        {
            title: "Install Agenta AI",
            code: "pip install -U agenta",
        },
        {
            title: "Clone the example application",
            code: "git clone https://github.com/Agenta-AI/simple_prompt && cd simple_prompt",
        },
        {
            title: "Set up environement variable",
            code: 'echo -e "OPENAI_API_KEY=sk-xxx" > .env',
        },
        {
            title: "Setup Agenta (select start from blank)",
            code: "agenta init",
        },
        {
            title: "Serve an app variant",
            code: "agenta variant serve --file_name app.py",
        },
    ]
    return (
        <section className={classes.modal}>
            <div className="flex items-center justify-between">
                <Space className={classes.headerText}>
                    {hasApps && (
                        <Button
                            icon={<ArrowLeft size={14} />}
                            className="flex items-center justify-center"
                            onClick={() => setCurrent(0)}
                        />
                    )}

                    <Typography.Text>Write your own app</Typography.Text>
                </Space>

                <Typography.Link href="https://www.youtube.com/watch?v=nggaRwDZM-0" target="_blank">
                    <Button icon={<Play size={14} className="mt-[2px]" />} className="mr-6">
                        Tutorial
                    </Button>
                </Typography.Link>
            </div>

            <Text>
                Create your own complex application using any framework. To learn more about how to
                write your own LLM app here,{" "}
                <a href="#" className="!underline !underline-offset-2">
                    Click here
                </a>
            </Text>

            {listOfCommands.map((item, ind) => (
                <div className="grid gap-4">
                    {item.title.includes("API Key") ? (
                        <div className="space-y-2">
                            <Text className={classes.label}>
                                Step {ind}: {item.title}
                            </Text>
                            <Button
                                className="block"
                                onClick={() => router.push("/settings?tab=apiKeys")}
                            >
                                Get an API key
                            </Button>
                        </div>
                    ) : (
                        <div className="space-y-2">
                            <Text className={classes.label}>
                                Step {ind}: {item.title}
                            </Text>

                            <div className="flex items-center justify-between gap-2">
                                <div className={classes.command}>{item.code}</div>

                                <Button
                                    onClick={() => onCopyCode(item.code, ind)}
                                    icon={
                                        isCopied !== ind ? <Copy size={14} /> : <Check size={14} />
                                    }
                                    className={classes.copyBtn}
                                />
                            </div>
                        </div>
                    )}
                </div>
            ))}
        </section>
    )
}

export default WriteOwnAppModal
