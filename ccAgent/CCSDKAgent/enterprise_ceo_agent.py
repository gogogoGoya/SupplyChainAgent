#!/usr/bin/env python3
"""
企业CEO模拟Agent
基于Claude Agent SDK实现"分析-计划-行动"工作流
"""

import anyio
import json
import time
import copy
import asyncio
import os
from pathlib import Path
import sys
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    query,
    AssistantMessage,
    TextBlock,
    ResultMessage
)
from static_utils import StaticUtils
from token_tracker import TokenTracker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from config.environment_config import EnvironmentConfig

class EnterpriseCEOClient:
    """企业CEO模拟客户端"""
    
    def __init__(self, client_dir: str):
        """
        初始化企业CEO客户端
        
        Args:
            client_dir: 客户端目录路径
        """
        print("Path(client_dir)",Path(client_dir))
        self.client_dir = Path(client_dir)
        self.workspace_dir = self.client_dir / "workspace"
        self.guidance_dir = self.client_dir / "guidance"
        # self.token_tracker = TokenTracker(self.workspace_dir)
        
        # 配置Claude Agent选项
        self.options = ClaudeAgentOptions(
            cwd=str(self.client_dir),
            allowed_tools=["Read", "Write", "Bash", "Skill"],
            permission_mode='acceptEdits',
            setting_sources=["project"],
            include_partial_messages=False,
            system_prompt=self._get_system_prompt(),
            model=EnvironmentConfig.DEFAULT_CEO_MODEL,
            env=EnvironmentConfig.get_agent_env(),
        )
    
    def _get_system_prompt(self) -> str:
        """获取系统提示"""
        return """
你是一个企业CEO，负责管理整个企业的运营。你需要通过调用自身可用的skills来推进整个企业的发展。
        """.strip()
    
    async def _execute_bash_command(self, command: str) -> str:
        """执行bash命令"""
        async with ClaudeSDKClient(options=self.options) as client:
            async for message in query(
                prompt=f"请执行bash命令：{command}，并返回执行结果",
                options=self.options
            ):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            return block.text
        return ""

    async def run_department(self, dept, round_id, option_now):
        role = dept["role"]
        skill_name = dept["name"]
        execute_func = dept["execute"]

        prompt = f"现在是第{round_id}个工作日，调用你的{skill_name}技能"

        success = False
        retry_time = 0
        local_messages = []
        
        options = ClaudeAgentOptions(**vars(option_now))
        options_session_id = ""
        timeout = 100
        while not success and retry_time < 3:
            print(f"TEST--START-{retry_time}", dept["name"])
            time_start = time.time()
            last_message = None
            try:
                async def stream():
                    nonlocal last_message, success, retry_time, prompt, timeout, options_session_id
                    async for message in query(prompt=prompt, options=options):
                        local_messages.append({
                            "role": role,
                            "content": str(message)
                        })

                        session_id = getattr(message, "data", {}).get("session_id")
                        if session_id:
                            options_session_id = session_id
                        last_message = message
                    # if isinstance(last_message, ResultMessage):
                    #     self.token_tracker.record(round_id, role, last_message)
                    result = execute_func(round_id, retry_time)
                    success = result.get("status") == "success"
                    if not success:
                        error_file = result.get("file_path")
                        prompt = (
                            f"现在是第{round_id}个工作日,"
                            f"你此前通过{skill_name}技能生成的行动方法存在错误，"
                            f"错误信息存储在/{error_file} 文件中，"
                            f"请重新调用该技能生成新的方案"
                        )
                        if options_session_id:
                            options.resume = options_session_id
                        retry_time += 1
                        timeout = 120
                    time_end = time.time()
                    print(f"TEST--END-{retry_time}", dept["name"], f"耗时: {time_end - time_start}")

                await asyncio.wait_for(stream(), timeout=timeout)
            except asyncio.TimeoutError:
                print("query timeout")
                retry_time += 1
        return local_messages


    async def handle_department_action(self, round_id, option_now, messages):
        departments = [
            {
                "role": "HR",
                "name": "人力资源管理管理(HR)",
                "execute": StaticUtils.execute_hr_action
            },
            {
                "role": "Sales",
                "name": "销售部门管理(Sales)",
                "execute": StaticUtils.execute_sales_action
            },
            {
                "role": "Production",
                "name": "产品生产部门管理(Production)",
                "execute": StaticUtils.execute_production_action
            },
            {
                "role": "Inventory",
                "name": "库存管理(Inventory)",
                "execute": StaticUtils.execute_inventory_action
            },
            {
                "role": "Procurement",
                "name": "采购部门管理(Procurement)",
                "execute": StaticUtils.execute_procurement_action
            }
        ]

        tasks = [
            asyncio.create_task(
                self.run_department(dept, round_id, option_now)
            )
            for dept in departments
        ]

        results = await asyncio.gather(*tasks)

        for r in results:
            messages.extend(r)

        return messages

    async def run_workflow(self, round_id: int):

        messages = []
        analyst_sessionId = None
        StaticUtils.handle_daily_action()
        filepath = StaticUtils.save_observation()
        time_start = time.time()
        print(f"TEST--START-{round_id} Analyst")
        last_message = None
        analyst_prompt = f"现在是第{round_id}个工作日，调用你的企业状态分析(Analyst)技能,并最终按要求输出一份analysis.json 文件"
        async for message in query(prompt=analyst_prompt, options=self.options):
            messages.append({
                "role": "Analyst",
                "content": str(message)
            })
            # print("Analysis Message:",message)
            session_id = getattr(message, "data", {}).get("session_id")
            if session_id:
                analyst_sessionId = session_id
            last_message = message
        # if isinstance(last_message, ResultMessage):
        #     self.token_tracker.record(round_id, "Analyst", last_message)
        time_end = time.time()
        print(f"TEST--END-{round_id} Analyst", f"耗时: {time_end - time_start}")
        StaticUtils.handle_observation(input_file=filepath,round_id=round_id)

        option_now = self.options
        # if analyst_sessionId:
        #     option_now.resume = analyst_sessionId

        messages = await self.handle_department_action(round_id, option_now,messages)

        StaticUtils.extract_failed()

        # 再次执行刷新记录的文本数据
        filepath_2 = StaticUtils.save_observation()
        StaticUtils.handle_observation(input_file=filepath_2,isDayEnd=True,round_id=round_id)

        StaticUtils.save_messages(round_id, messages)
        StaticUtils.archive_json_files(round_id=round_id)
        StaticUtils.run_day()

        # self.token_tracker.save_report()
        # self.token_tracker.print_summary()

async def run(max_step, type: str = "test"):
    """从零开始运行模拟"""
    # 初始化企业CEO客户端
    ceo_client = EnterpriseCEOClient(
       client_dir=str(Path(__file__).parent.absolute())
    )
    # 运行工作流
    max_step = max_step

    StaticUtils.handle_init_action()
    for step in range(max_step):
        await ceo_client.run_workflow(round_id=step)
    if type == "run":
        StaticUtils.archive_workspace()
        

async def run_with_history(workspace_name: str, reproduction_step: int, max_step: int, type: str = "test"):
    """
        根据已有内容，指定模拟天数开始运行
    Args:
        workspace_name: history目录下待复现的模拟目录名称
        reproduction_step: 要复现的step数
        max_step: 后续要继续模拟到的最终step数(实际思考轮数为max_step-reproduction_step)
    """
    ceo_client = EnterpriseCEOClient(
       client_dir=str(Path(__file__).parent.absolute())
    )
    StaticUtils.handle_reproduction(workspace_name, reproduction_step)
    filepath = StaticUtils.save_observation()
    # 要在已有基础上额外运行的轮次
    for step in range(reproduction_step,max_step):
        await ceo_client.run_workflow(round_id=step)
    if type == "run":
        StaticUtils.archive_workspace(workspace_name+"_restart_in_"+str(reproduction_step))


async def main():
    await run(1)
    # await run(20,"run")
    # await run_with_history("workspace_3.26_0",13,20)
    
    
if __name__ == "__main__":
    anyio.run(main)
